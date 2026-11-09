"""Order alerts: tell your phone when a new order comes in.

Three ways to reach the phone (use any mix):
  push   - free ntfy app (iPhone/Android). No account, no API key. Recommended.
  twilio - a real SMS text through Twilio (paid account + toll-free number verification).
  email  - an email through your Gmail (app password). Point it at your carrier's email-to-text
           address (Verizon until 31 Mar 2027, Google Fi, US Cellular...) or any inbox.
"""
import json
import logging
import secrets as pysecrets
import smtplib
import unicodedata
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .integrations.crypto import decrypt_secrets, encrypt_secrets
from .models import Integration, NotifySettings, Order, utcnow

log = logging.getLogger("oneshot.alerts")

CHANNELS = ("push", "twilio", "email")
SECRET_KEYS = ("push_token", "twilio_token", "gmail_app_password")
# Carrier email-to-text domains. AT&T (Jun 2025), T-Mobile (late 2024) and Cricket have shut theirs.
CARRIERS = {
    "verizon": ("Verizon (works until 31 Mar 2027)", "vtext.com"),
    "google_fi": ("Google Fi", "msg.fi.google.com"),
    "us_cellular": ("US Cellular", "email.uscc.net"),
    "tmobile": ("T-Mobile (unreliable, may not arrive)", "tmomail.net"),
    "custom": ("Other / any email address", ""),
}
SOURCE_NAMES = {"square": "Square", "ebay": "eBay", "tiktok_shop": "TikTok Shop"}
SKIP_STATES = {"CANCELED", "CANCELLED", "DRAFT"}
MAX_AGE = timedelta(days=3)          # older orders found later (history back-fill) don't alert
SEND_TIMEOUT = 15

DEFAULTS = {
    "enabled": False,
    "push_enabled": False, "push_server": "https://ntfy.sh", "push_topic": "",
    "twilio_enabled": False, "twilio_sid": "", "twilio_from": "", "twilio_to": "",
    "email_enabled": False, "email_from": "", "email_carrier": "verizon", "email_number": "", "email_to": "",
    "min_total": 0, "sources": [], "show_customer": True, "app_url": "",
}


# ---------------------------------------------------------------- settings
def _row(db: Session) -> NotifySettings:
    row = db.scalar(select(NotifySettings).limit(1))
    if row is None:
        cfg = {**DEFAULTS, "push_topic": f"funnelhub-{pysecrets.token_hex(6)}"}   # hard to guess = private
        row = NotifySettings(config=json.dumps(cfg))
        db.add(row)
        db.flush()
    return row


def load(db: Session) -> tuple[dict, dict]:
    row = _row(db)
    cfg = {**DEFAULTS, **json.loads(row.config or "{}")}
    try:
        sec = decrypt_secrets(row.secrets)
    except ValueError:
        sec = {}
    return cfg, sec


def gmail_connection(db: Session) -> tuple[str, str] | None:
    """Reuse the Gmail connection's address + app password when the alert settings leave them blank."""
    for integ in db.scalars(select(Integration).where(Integration.provider == "gmail")).all():
        try:
            sec = decrypt_secrets(integ.secrets)
        except ValueError:
            continue
        addr = json.loads(integ.config or "{}").get("email", "")
        if addr and sec.get("app_password"):
            return addr, sec["app_password"]
    return None


def email_target(cfg: dict) -> str:
    if (cfg.get("email_carrier") or "custom") == "custom":
        return (cfg.get("email_to") or "").strip()
    digits = "".join(c for c in str(cfg.get("email_number") or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    domain = CARRIERS.get(cfg["email_carrier"], ("", ""))[1]
    return f"{digits}@{domain}" if digits and domain else ""


def public(db: Session) -> dict:
    cfg, sec = load(db)
    gm = gmail_connection(db)
    return {"config": cfg, "saved_secrets": sorted(k for k in SECRET_KEYS if sec.get(k)),
            "gmail_connection": gm[0] if gm else "", "email_target": email_target(cfg),
            "carriers": [{"key": k, "label": v[0], "domain": v[1]} for k, v in CARRIERS.items()],
            "history": json.loads(_row(db).history or "[]")}


def save(db: Session, config: dict, new_secrets: dict, clear: list[str]) -> dict:
    row = _row(db)
    cfg, sec = load(db)
    for k, v in (config or {}).items():
        if k in DEFAULTS:
            cfg[k] = v
    cfg["push_topic"] = "".join(c for c in str(cfg.get("push_topic") or "") if c.isalnum() or c in "-_")[:64]
    cfg["push_server"] = (str(cfg.get("push_server") or "https://ntfy.sh").strip().rstrip("/")) or "https://ntfy.sh"
    try:
        cfg["min_total"] = max(0.0, float(cfg.get("min_total") or 0))
    except (TypeError, ValueError):
        cfg["min_total"] = 0.0
    for k, v in (new_secrets or {}).items():
        if k in SECRET_KEYS and str(v).strip():
            sec[k] = str(v).strip()
    for k in clear or []:
        sec.pop(k, None)
    row.config, row.secrets = json.dumps(cfg), encrypt_secrets(sec)
    db.commit()
    return public(db)


# ---------------------------------------------------------------- senders
def _ascii(text: str) -> str:
    """Carrier email-to-text gateways mangle anything but plain ASCII."""
    text = text.replace("×", "x").replace("–", "-").replace("—", "-").replace("…", "...").replace("•", "-")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def send_push(cfg: dict, sec: dict, title: str, body: str, click: str = "") -> None:
    topic = cfg.get("push_topic") or ""
    if not topic:
        raise ValueError("Push: no topic name set")
    params = {"title": title, "tags": "moneybag", "priority": "high"}
    if click:
        params["click"] = click
    headers = {"Authorization": f"Bearer {sec['push_token']}"} if sec.get("push_token") else {}
    with httpx.Client(timeout=SEND_TIMEOUT) as c:
        r = c.post(f"{cfg.get('push_server') or 'https://ntfy.sh'}/{topic}", params=params,
                   content=body.encode(), headers=headers)
    if r.status_code >= 400:
        raise ValueError(f"Push: server said {r.status_code} {r.text[:200]}")


def send_twilio(cfg: dict, sec: dict, text: str) -> None:
    sid, token = (cfg.get("twilio_sid") or "").strip(), sec.get("twilio_token") or ""
    frm, to = (cfg.get("twilio_from") or "").strip(), (cfg.get("twilio_to") or "").strip()
    if not (sid and token and frm and to):
        raise ValueError("Twilio: fill in Account SID, Auth Token, From number and Your phone")
    with httpx.Client(timeout=SEND_TIMEOUT) as c:
        r = c.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                   auth=(sid, token), data={"From": frm, "To": to, "Body": text[:320]})
    if r.status_code >= 400:
        try:
            err = r.json()
            msg = f"{err.get('message')} (code {err.get('code')})"
        except ValueError:
            msg = r.text[:200]
        if "30032" in msg or "21608" in msg or "unverified" in msg.lower():
            msg += " - your Twilio number still needs toll-free verification, or you're on a trial"
        raise ValueError(f"Twilio: {msg}")


def send_email(db: Session, cfg: dict, sec: dict, subject: str, text: str) -> None:
    to = email_target(cfg)
    if not to:
        raise ValueError("Text by email: enter your phone number (or an email address)")
    sender, password = (cfg.get("email_from") or "").strip(), sec.get("gmail_app_password") or ""
    if not (sender and password):
        gm = gmail_connection(db)
        if not gm:
            raise ValueError("Text by email: enter a Gmail address + app password, or connect Gmail on Integrations")
        sender, password = gm
    is_gateway = (cfg.get("email_carrier") or "custom") != "custom"
    msg = EmailMessage()
    msg["From"], msg["To"] = sender, to
    msg["Subject"] = _ascii(subject) if is_gateway else subject
    msg.set_content(_ascii(text)[:300] if is_gateway else text)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=SEND_TIMEOUT) as s:
            s.starttls()
            s.login(sender, password.replace(" ", ""))
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise ValueError("Text by email: Gmail rejected the app password (make a new one at "
                         "myaccount.google.com/apppasswords)") from e
    except (smtplib.SMTPException, OSError) as e:
        raise ValueError(f"Text by email: {type(e).__name__}: {e}") from e


def deliver(db: Session, title: str, body: str, short: str, click: str = "", only: str | None = None,
            force: bool = False) -> dict:
    """Send to every turned-on channel. Returns {"push": "ok" | "error text", ...}."""
    cfg, sec = load(db)
    results: dict[str, str] = {}
    for ch in CHANNELS:
        if only and ch != only:
            continue
        if not (force and only) and not cfg.get(f"{ch}_enabled"):
            continue
        try:
            if ch == "push":
                send_push(cfg, sec, title, body, click)
            elif ch == "twilio":
                send_twilio(cfg, sec, short)
            else:
                send_email(db, cfg, sec, title, short)
            results[ch] = "ok"
        except Exception as e:  # one broken channel must not stop the others
            results[ch] = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
            log.warning("alert via %s failed: %s", ch, results[ch])
    return results


def _remember(db: Session, kind: str, title: str, results: dict) -> None:
    row = _row(db)
    hist = json.loads(row.history or "[]")
    hist.insert(0, {"at": utcnow().isoformat(), "kind": kind, "title": title, "results": results})
    row.history = json.dumps(hist[:25])
    db.commit()


# ---------------------------------------------------------------- order alerts
def _money(amount: float, cur: str) -> str:
    return f"${amount:,.2f}" if (cur or "USD").upper() == "USD" else f"{amount:,.2f} {cur}"


def _link(cfg: dict) -> str:
    base = (cfg.get("app_url") or "").strip().rstrip("/")
    return f"{base}/orders" if base else ""


def format_order(o: Order, show_customer: bool = True) -> tuple[str, str, str]:
    src = SOURCE_NAMES.get(o.source, o.source.replace("_", " ").title())
    amount = _money(o.total or o.net or 0, o.currency)
    title = f"New order {amount} - {src}"
    who = (o.customer_name or o.buyer_username or "").strip() if show_customer else ""
    items = (o.items_summary or "").strip()
    lines = [x for x in (who, items[:200], f"Order #{o.reference}" if o.reference else "") if x]
    body = "\n".join(lines) or "Open the CRM to see it."
    short = f"FunnelHub: new {src} order {amount}" + (f" - {who}" if who else "") + (f" - {items[:80]}" if items else "")
    return title, body, short


def max_order_id(db: Session) -> int:
    return int(db.scalar(select(func.coalesce(func.max(Order.id), 0))) or 0)


def order_alerts(db: Session, after_id: int, channel_id: int | None = None) -> list[dict]:
    """Alert for orders created after ``after_id`` (called right after a sync)."""
    cfg, _ = load(db)
    if not cfg.get("enabled") or not any(cfg.get(f"{c}_enabled") for c in CHANNELS):
        return []
    stmt = select(Order).where(Order.id > after_id).order_by(Order.id)
    if channel_id:
        stmt = stmt.where(Order.channel_id == channel_id)
    cutoff = utcnow() - MAX_AGE
    sources = set(cfg.get("sources") or [])
    new = [o for o in db.scalars(stmt).all()
           if (o.state or "").upper() not in SKIP_STATES
           and (o.ordered_at is None or o.ordered_at >= cutoff)
           and (not sources or o.source in sources)
           and (o.total or o.net or 0) >= float(cfg.get("min_total") or 0)]
    if not new:
        return []
    sent = []
    if len(new) > 3:   # a burst (e.g. first sync after downtime) -> one summary, not a flood
        total = sum(o.total or o.net or 0 for o in new)
        title = f"{len(new)} new orders - {_money(total, new[0].currency)}"
        names = ", ".join(sorted({SOURCE_NAMES.get(o.source, o.source) for o in new}))
        body = f"From {names}. Open Orders in the CRM to see them."
        short = f"FunnelHub: {len(new)} new orders, {_money(total, new[0].currency)} ({names})"
        res = deliver(db, title, body, short, _link(cfg))
        _remember(db, "orders", title, res)
        sent.append({"title": title, "results": res})
    else:
        for o in new:
            title, body, short = format_order(o, cfg.get("show_customer", True))
            res = deliver(db, title, body, short, _link(cfg))
            _remember(db, "order", title, res)
            sent.append({"title": title, "results": res})
    log.info("order alerts: %s", "; ".join(f"{s['title']} -> {s['results']}" for s in sent))
    return sent


def send_test(db: Session, only: str | None = None) -> dict:
    cfg, _ = load(db)
    title = "Test order alert - FunnelHub"
    body = "This is what a new order alert looks like.\nJane Doe - 2x Hat\nOrder #TEST01"
    short = "FunnelHub: test order alert $25.00 - Jane Doe - 2x Hat"
    res = deliver(db, title, body, short, _link(cfg), only=only, force=True)
    if not res:
        res = {"none": "Turn on at least one way to alert you first"}
    _remember(db, "test", title, res)
    return res

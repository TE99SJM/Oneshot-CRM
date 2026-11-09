"""Gmail: emails with your contacts -> Emails tab and each contact's history (IMAP + Google app password).

Why IMAP instead of the Gmail API: reading Gmail through Google's API needs a "restricted" scope, and a
personal (unverified, Testing) Google Cloud app has its sign-in expire every 7 days.  An app password
over IMAP keeps working until you revoke it, and needs no Google Cloud project.
"""
import imaplib
import json
import re
import socket
from datetime import timedelta, timezone
from email import message_from_bytes, policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html import unescape

from sqlalchemy import func, select

from ..models import Contact, Email, utcnow
from .base import FAST_INTERVAL, FieldSpec, ProviderInfo, SyncContext, SyncError

HOST = "imap.gmail.com"
BATCH = 25
MAX_PER_SYNC = 1500
MAX_FULL_SIZE = 3_000_000          # bigger messages are saved without their body (open them in Gmail)
TEXT_LIMIT, HTML_LIMIT = 100_000, 400_000
SKIP_CATEGORIES = "-category:promotions -category:social -category:updates -category:forums"

INFO = ProviderInfo(
    key="gmail", name="Gmail", platform="gmail", channel_kind="email",
    summary="Emails with your contacts show up in an Emails tab and on each contact.",
    syncs=["Sent and received emails → Emails tab (full message, attachments list)",
           "Emails are linked to matching contacts and shown on their page",
           "Optional: people you email become contacts",
           "Read-only: the CRM never sends, deletes or marks mail"],
    fields=[
        FieldSpec("email", "Gmail address", placeholder="you@gmail.com"),
        FieldSpec("app_password", "Google app password", secret=True, placeholder="abcd efgh ijkl mnop",
                  help="16 letters from myaccount.google.com/apppasswords (needs 2-Step Verification). "
                       "Not your normal Google password."),
        FieldSpec("mail", "Which mail", kind="select", options=["primary", "all"], default="primary", required=False,
                  help="primary = Primary inbox tab + Sent (skips Promotions, Social, Updates, Forums). all = everything except spam/trash."),
        FieldSpec("create_contacts", "New contacts from email", kind="select", options=["emailed", "all", "none"],
                  default="emailed", required=False,
                  help="emailed = add people you've sent mail to. all = also people who email you (newsletters and no-reply are skipped). "
                       "none = only link emails to contacts you already have."),
        FieldSpec("history_days", "Days of history on first sync", required=False, default="90", placeholder="90"),
        FieldSpec("aliases", "Other addresses that are you (optional)", required=False,
                  placeholder="sales@theforge.com, me@otherdomain.com",
                  help="Mail sent from these counts as sent by you."),
    ],
    steps=[
        "Turn on 2-Step Verification for your Google account at myaccount.google.com/security (skip if it's already on).",
        "Open myaccount.google.com/apppasswords, type a name like “Oneshot CRM” and click Create.",
        "Copy the 16-letter password Google shows (spaces are fine) and paste it here with your Gmail address.",
        "Click Connect & sync. The first sync reads the last 90 days. After that only new mail is read.",
        "To cut the CRM off later, delete the app password at myaccount.google.com/apppasswords.",
    ],
    docs_url="https://support.google.com/accounts/answer/185833",
    default_interval=FAST_INTERVAL,
)


def make_imap(host: str):
    """Factory so tests can swap in a fake server."""
    return imaplib.IMAP4_SSL(host, 993, timeout=60)


# ------------------------------------------------------------------------------------------------ connection
def _connect(ctx: SyncContext):
    user = (ctx.config.get("email") or "").strip()
    pw = re.sub(r"\s+", "", ctx.secrets.get("app_password", ""))
    if not user or not pw:
        raise SyncError("Gmail: enter your Gmail address and app password")
    try:
        imap = make_imap(HOST)
    except (OSError, socket.timeout) as e:
        raise SyncError(f"Gmail: couldn't reach {HOST} ({e}). Check the server's internet connection.") from e
    try:
        imap.login(user, pw)
    except imaplib.IMAP4.error as e:
        msg = str(e)
        if "AUTHENTICATIONFAILED" in msg or "Invalid credentials" in msg or "Application-specific password" in msg:
            raise SyncError("Gmail: Google rejected the sign-in. Use an app password from myaccount.google.com/apppasswords "
                            "(not your normal password), and check the address.") from e
        raise SyncError(f"Gmail: sign-in failed ({msg})") from e
    return imap


def _all_mail_folder(imap) -> str:
    typ, data = imap.list()
    for line in data or []:
        s = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
        if "\\All" in s:
            m = re.search(r'"([^"]+)"\s*$', s) or re.search(r"\s(\S+)\s*$", s)
            if m:
                return m.group(1)
    return "[Gmail]/All Mail"


def _select(imap, folder: str) -> int:
    typ, _ = imap.select(f'"{folder}"', readonly=True)
    if typ != "OK":
        raise SyncError(f"Gmail: couldn't open the {folder} folder")
    typ, data = imap.response("UIDVALIDITY")
    try:
        return int((data or [b"0"])[0])
    except (TypeError, ValueError):
        return 0


def test(ctx: SyncContext) -> str:
    imap = _connect(ctx)
    try:
        folder = _all_mail_folder(imap)
        _select(imap, folder)
        typ, data = imap.uid("SEARCH", None, "X-GM-RAW", '"newer_than:7d"')
        n = len((data or [b""])[0].split())
        return f"Connected to {ctx.config.get('email')} ({n} messages in the last 7 days)"
    finally:
        _logout(imap)


def _logout(imap):
    try:
        imap.logout()
    except Exception:
        pass


# ------------------------------------------------------------------------------------------------ parsing
_META = {
    "uid": re.compile(rb"UID (\d+)"),
    "thrid": re.compile(rb"X-GM-THRID (\d+)"),
    "msgid": re.compile(rb"X-GM-MSGID (\d+)"),
    "size": re.compile(rb"RFC822\.SIZE (\d+)"),
    "flags": re.compile(rb"FLAGS \(([^)]*)\)"),
    "labels": re.compile(rb"X-GM-LABELS \(((?:[^()\"]|\"(?:[^\"\\\\]|\\\\.)*\")*)\)"),
}


def _parse_fetch(data) -> list[tuple[dict, bytes]]:
    """imaplib FETCH response -> [(meta, literal_bytes)]."""
    out, i = [], 0
    while i < len(data):
        part = data[i]
        if isinstance(part, tuple):
            head, lit = part[0], part[1]
            tail = data[i + 1] if i + 1 < len(data) and isinstance(data[i + 1], bytes) else b""
            meta_src = head + b" " + tail
            meta = {k: (r.search(meta_src).group(1) if r.search(meta_src) else b"") for k, r in _META.items()}
            out.append((meta, lit))
        elif isinstance(part, bytes) and b"UID" in part and b"{" not in part:
            meta = {k: (r.search(part).group(1) if r.search(part) else b"") for k, r in _META.items()}
            out.append((meta, b""))
        i += 1
    return out


def _labels(raw: bytes) -> list[str]:
    s = raw.decode(errors="replace")
    return [unescape(m.group(1) or m.group(2)).replace('\\"', '"') for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|(\S+)', s)]


def _addr_list(values) -> list[tuple[str, str]]:
    return [(n.strip(), a.strip().lower()) for n, a in getaddresses([str(v) for v in values if v]) if a and "@" in a]


def _fmt(addrs) -> str:
    return ", ".join(f"{n} <{a}>" if n else a for n, a in addrs)


def _strip_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    return re.sub(r"[ \t\r\f\v]+", " ", unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def _bodies(msg) -> tuple[str, str, list[dict]]:
    text = html = ""
    try:
        part = msg.get_body(preferencelist=("plain",))
        if part is not None:
            text = part.get_content()
    except Exception:
        pass
    try:
        part = msg.get_body(preferencelist=("html",))
        if part is not None:
            html = part.get_content()
    except Exception:
        pass
    atts = []
    try:
        for a in msg.iter_attachments():
            try:
                size = len(a.get_payload(decode=True) or b"")
            except Exception:
                size = 0
            atts.append({"name": a.get_filename() or "(unnamed)", "type": a.get_content_type(), "size": size})
    except Exception:
        pass
    if not text and html:
        text = _strip_html(html)
    return text[:TEXT_LIMIT], html[:HTML_LIMIT], atts


def _is_bulk(msg, from_addr: str) -> bool:
    if msg.get("List-Unsubscribe") or msg.get("List-Id"):
        return True
    if (msg.get("Precedence") or "").lower() in ("bulk", "list", "junk"):
        return True
    return bool(re.search(r"(no-?reply|do-?not-?reply|notifications?|mailer-daemon|newsletter|bounce)", from_addr))


# ------------------------------------------------------------------------------------------------ contacts
def _contact_map(ctx) -> dict[str, Contact]:
    return {c.email.lower(): c for c in ctx.db.scalars(select(Contact).where(Contact.email != "")).all()}


def _get_or_create(ctx, contacts: dict, name: str, addr: str, create: bool) -> Contact | None:
    c = contacts.get(addr)
    if c is None and create:
        first, _, last = (name or addr.split("@")[0]).replace('"', "").partition(" ")
        c = Contact(first_name=first[:80] or addr[:80], last_name=last[:80], email=addr, status="lead",
                    source_channel_id=ctx.channel.id, tags="email", external_source="gmail", external_id=addr)
        ctx.db.add(c)
        ctx.db.flush()
        contacts[addr] = c
        ctx.count("contacts_created")
    return c


# ------------------------------------------------------------------------------------------------ sync
def sync(ctx: SyncContext) -> None:
    account = (ctx.config.get("email") or "").strip().lower()
    me = {account} | {a.strip().lower() for a in (ctx.config.get("aliases") or "").split(",") if "@" in a}
    mode = ctx.config.get("mail") or "primary"
    create = ctx.config.get("create_contacts") or "emailed"
    days = max(1, min(int(ctx.config.get("history_days") or 90), 3650))

    imap = _connect(ctx)
    try:
        folder = _all_mail_folder(imap)
        uidvalidity = _select(imap, folder)
        last_uid = ctx.db.scalar(select(func.max(Email.uid)).where(Email.account == account,
                                                                  Email.uidvalidity == uidvalidity)) or 0
        raw = "-in:drafts -in:chats" + (f" {SKIP_CATEGORIES}" if mode == "primary" else "")
        if last_uid:
            crit = ("UID", f"{last_uid + 1}:*", "X-GM-RAW", f'"{raw}"')
        else:
            since = (utcnow() - timedelta(days=days)).strftime("%Y/%m/%d")
            crit = ("X-GM-RAW", f'"after:{since} {raw}"')
        typ, data = imap.uid("SEARCH", None, *crit)
        if typ != "OK":
            raise SyncError("Gmail: search failed")
        uids = sorted(u for u in (int(x) for x in (data or [b""])[0].split()) if u > last_uid)
        if len(uids) > MAX_PER_SYNC:
            ctx.warnings.append(f"{len(uids) - MAX_PER_SYNC} more emails will be read on the next syncs.")
            uids = uids[:MAX_PER_SYNC]
        contacts = _contact_map(ctx)
        known = set(ctx.db.scalars(select(Email.gm_msgid).where(Email.account == account)).all())

        for i in range(0, len(uids), BATCH):
            chunk = ",".join(str(u) for u in uids[i:i + BATCH])
            typ, data = imap.uid("FETCH", chunk, "(UID X-GM-THRID X-GM-MSGID X-GM-LABELS FLAGS RFC822.SIZE)")
            metas = {int(m["uid"]): m for m, _ in _parse_fetch(data or []) if m["uid"]}
            small = [u for u, m in metas.items() if int(m["size"] or 0) <= MAX_FULL_SIZE]
            big = [u for u in metas if u not in small]
            bodies: dict[int, bytes] = {}
            for want, item in ((small, "BODY.PEEK[]"), (big, "BODY.PEEK[HEADER]")):
                if not want:
                    continue
                typ, data = imap.uid("FETCH", ",".join(map(str, want)), f"(UID {item})")
                for m, lit in _parse_fetch(data or []):
                    if m["uid"]:
                        bodies[int(m["uid"])] = lit
            for uid in sorted(metas):
                meta = metas[uid]
                gm = meta["msgid"].decode()
                if gm and gm in known:
                    continue
                _save(ctx, account, me, create, uidvalidity, uid, meta, bodies.get(uid, b""), uid in big, contacts)
                known.add(gm)
            ctx.db.flush()
    finally:
        _logout(imap)
    _relink(ctx, account, me)


def _relink(ctx, account: str, me: set[str]) -> None:
    """Link earlier emails to contacts that were added after the email was synced."""
    contacts = _contact_map(ctx)
    if not contacts:
        return
    rows = ctx.db.scalars(select(Email).where(Email.account == account, Email.contact_id.is_(None), Email.bulk.is_(False))
                          .order_by(Email.sent_at.desc()).limit(5000)).all()
    for e in rows:
        addrs = [e.from_email] if e.direction == "in" else [a for _, a in _addr_list([e.to_addrs, e.cc_addrs])]
        c = next((contacts[a] for a in addrs if a in contacts and a not in me), None)
        if c:
            e.contact_id = c.id
            ctx.count("emails_linked")


def _save(ctx, account, me, create, uidvalidity, uid, meta, raw: bytes, too_big: bool, contacts) -> None:
    msg = message_from_bytes(raw or b"", policy=policy.default)
    from_name, from_addr = parseaddr(str(msg.get("From", "")))
    from_addr = from_addr.lower()
    to = _addr_list(msg.get_all("To", []))
    cc = _addr_list(msg.get_all("Cc", []))
    outgoing = from_addr in me
    try:
        sent = parsedate_to_datetime(str(msg.get("Date"))).astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError):
        sent = utcnow()
    text, html, atts = ("", "", []) if too_big else _bodies(msg)
    if too_big:
        text = "(This message is too large to store in the CRM. Open it in Gmail.)"
    bulk = (not outgoing) and _is_bulk(msg, from_addr)

    # who is this email "with"?
    others = [(n, a) for n, a in (to + cc if outgoing else [(from_name, from_addr)]) if a not in me]
    contact = None
    allow = (outgoing and create in ("emailed", "all")) or (not outgoing and create == "all" and not bulk)
    for n, a in others:
        c = _get_or_create(ctx, contacts, n, a, allow)
        contact = contact or c

    labels = [l for l in _labels(meta["labels"]) if l]
    e = Email(account=account, uid=uid, uidvalidity=uidvalidity, gm_msgid=meta["msgid"].decode(),
              thread_id=meta["thrid"].decode(), message_id=str(msg.get("Message-ID", ""))[:500],
              direction="out" if outgoing else "in", from_name=from_name[:200], from_email=from_addr[:255],
              to_addrs=_fmt(to), cc_addrs=_fmt(cc), subject=str(msg.get("Subject", "") or "(no subject)")[:500],
              snippet=re.sub(r"\s+", " ", text)[:300], body_text=text, body_html=html, attachments=json.dumps(atts),
              labels=", ".join(labels)[:1000], unread=b"\\Seen" not in meta["flags"], bulk=bulk, sent_at=sent,
              contact_id=contact.id if contact else None, channel_id=ctx.channel.id)
    ctx.db.add(e)
    ctx.count("emails_sent" if outgoing else "emails_received")
    if contact:
        ctx.count("emails_linked")

"""TikTok Shop: every order with buyer, items, payment and shipping → Orders tab, buyers → Contacts, a
"TikTok Shop Sales" funnel, buyer chats → Messages, product counts, and "mark as shipped" with tracking.

Docs (Partner Center): sign requests https://partner.tiktokshop.com/docv2/page/sign-your-api-request ,
authorization https://partner.tiktokshop.com/docv2/page/authorization-overview-202407 , orders
https://partner.tiktokshop.com/docv2/page/get-order-list-202309 , customer service
https://partner.tiktokshop.com/docv2/page/get-conversations-202309
"""
import hashlib
import hmac
import json
import time
from collections import Counter
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy import select

from ..models import Contact, Deal, Order, utcnow
from .base import FAST_INTERVAL, FieldSpec, ProviderInfo, SyncContext, SyncError, find_external
from .messages_store import from_ts, refresh_summary, upsert_conversation, upsert_message
from .oauth_apps import require_signed_in, save_tokens
from .square import _funnel

OAUTH_SLUG = "tiktok-shop"
OAUTH_NAME = "TikTok Shop"
API = "https://open-api.tiktokglobalshop.com"
AUTH_API = "https://auth.tiktok-shops.com"
FUNNEL_NAME = "TikTok Shop Sales"
STAGES = ("Needs shipping", "Shipped", "Canceled")
MAX_ORDERS = 5000
SOURCE = "tiktok_shop"

OPEN = {"UNPAID", "ON_HOLD", "AWAITING_SHIPMENT", "PARTIALLY_SHIPPING"}
SHIPPED = {"AWAITING_COLLECTION", "IN_TRANSIT", "DELIVERED", "COMPLETED"}
FULFILLMENT = {"UNPAID": "AWAITING_PAYMENT", "ON_HOLD": "ON_HOLD", "AWAITING_SHIPMENT": "NEEDS_SHIPPING",
               "PARTIALLY_SHIPPING": "PARTLY_SHIPPED", "AWAITING_COLLECTION": "AWAITING_PICKUP",
               "IN_TRANSIT": "SHIPPED", "DELIVERED": "DELIVERED", "COMPLETED": "DELIVERED", "CANCELLED": "CANCELED"}

INFO = ProviderInfo(
    key="tiktok_shop", name="TikTok Shop", platform="tiktok", channel_kind="marketplace",
    summary="Every TikTok Shop order with buyer, items, payment and shipping, buyer chats, and product counts. "
            "Mark seller-shipped orders as shipped with tracking.",
    syncs=["Every order with full details → Orders tab", "Buyers → Contacts",
           "Orders → deals in a TikTok Shop Sales funnel", "Buyer chats → Messages (reply from the CRM)",
           "Products (live / total)", "Mark as shipped with tracking"],
    fields=[
        FieldSpec("app_key", "App key", help="Partner Center → App & Service → your app → App key."),
        FieldSpec("app_secret", "App secret", secret=True),
        FieldSpec("service_id", "Service ID", help="Partner Center → your app → Authorization → the number in the "
                                                     "authorization link (service_id=…)."),
        FieldSpec("region", "Shop region", kind="select", options=["US", "Other (global)"], default="US"),
        FieldSpec("history_days", "Days of orders on first sync", required=False, default="365",
                  help="Later syncs only fetch orders that changed."),
        FieldSpec("messages_every_minutes", "Check buyer messages every (minutes)", required=False, default="5",
                  help="Buyer chats are checked this often, separately from the full sync. 0 = only with the full sync."),
        FieldSpec("shop_id", "Shop ID (only if you have several shops)", required=False,
                  help="Leave blank to use your first shop."),
    ],
    docs_url="https://partner.tiktokshop.com/docv2/page/authorization-overview-202407",
    default_interval=FAST_INTERVAL,
    steps=[
        "Go to partner.tiktokshop.com and sign up as a developer (choose “Seller in-house developer” / custom app "
        "for your own shop). Link it to your TikTok Shop seller account.",
        "Create an app (Custom app). In its settings add the API scopes: Order information, Product basic, "
        "Fulfillment basic, Logistics basic, Customer service (seller.customer_service) and Shop authorized information.",
        "Set the app's Redirect URL to the return address the CRM shows after you save (your Tailscale Funnel address "
        "ending in /api/oauth/tiktok-shop/callback).",
        "Copy the App key, App secret and Service ID into this form and save, then click “Sign in” on the TikTok Shop card.",
        "TikTok has to approve the app (and the Customer Service scope) before live data flows. Approval for an "
        "in-house app for your own shop is usually quicker than for public apps.",
    ],
)


class ShopApiError(SyncError):
    """A TikTok Shop API error; .permission is True when the app lacks an approved scope."""
    def __init__(self, msg: str, code=None, permission: bool = False):
        super().__init__(msg)
        self.code, self.permission = code, permission


PERMISSION_CODES = {105001, 105002, 105005, 106001, 36009003, 36009004}
PERMISSION_WORDS = ("scope", "permission", "not authorized", "unauthorized", "access denied", "no access", "not authorised")


def is_permission_error(e: Exception) -> bool:
    if isinstance(e, ShopApiError) and e.permission:
        return True
    return isinstance(e, SyncError) and any(w in str(e).lower() for w in PERMISSION_WORDS)


# ---------------------------------------------------------------- signing
def sign(path: str, query: dict, body: bytes, secret: str, multipart: bool = False) -> str:
    """HMAC-SHA256 per Partner Center: secret + path + sorted key/values + body + secret."""
    keys = sorted(k for k in query if k not in ("sign", "access_token"))
    s = path + "".join(f"{k}{query[k]}" for k in keys)
    if body and not multipart:
        s += body.decode()
    s = f"{secret}{s}{secret}"
    return hmac.new(secret.encode(), s.encode(), hashlib.sha256).hexdigest()


def _creds(config: dict, secrets: dict) -> tuple[str, str]:
    key, sec = (config.get("app_key") or "").strip(), (secrets.get("app_secret") or "").strip()
    if not key or not sec:
        raise SyncError("TikTok Shop: App key and App secret are required")
    return key, sec


# ---------------------------------------------------------------- sign-in
def authorize_url(config: dict, secrets: dict, redirect_uri: str, state: str) -> str:
    sid = (config.get("service_id") or "").strip()
    if not sid:
        raise SyncError("TikTok Shop: enter the Service ID first (Edit)")
    host = "services.us.tiktokshop.com" if (config.get("region") or "US") == "US" else "services.tiktokshop.com"
    return f"https://{host}/open/authorize?" + urlencode({"service_id": sid, "state": state})


def _token_call(client, path: str, params: dict) -> dict:
    resp = client.get(f"{AUTH_API}{path}", params=params)
    try:
        body = resp.json()
    except ValueError:
        raise SyncError(f"TikTok Shop sign-in: HTTP {resp.status_code} {resp.text[:200]}") from None
    if resp.status_code >= 400 or body.get("code") not in (0, None) or not (body.get("data") or {}).get("access_token"):
        raise SyncError(f"TikTok Shop sign-in failed: {body.get('message') or resp.text[:200]}")
    return body["data"]


def _token_fields(d: dict) -> dict:
    exp = int(d.get("access_token_expire_in") or 0)
    if exp and exp < 10**9:                     # seconds-from-now form, just in case
        exp += int(time.time())
    return {"access_token": d["access_token"], "refresh_token": d.get("refresh_token") or "",
            "token_expires": str((exp or int(time.time()) + 6 * 86400) - 300)}


def exchange(client, config: dict, secrets: dict, code: str, redirect_uri: str) -> dict:
    key, sec = _creds(config, secrets)
    d = _token_call(client, "/api/v2/token/get", {"app_key": key, "app_secret": sec, "auth_code": code,
                                                   "grant_type": "authorized_code"})
    tok = _token_fields(d)
    shops = _request(client, key, sec, tok["access_token"], "GET", "/authorization/202309/shops").get("shops") or []
    if not shops:
        raise SyncError("TikTok Shop: signed in, but no shop is authorized for this app")
    want = (config.get("shop_id") or "").strip()
    shop = next((s for s in shops if str(s.get("id")) == want), shops[0])
    return {"secrets": {**tok, "shop_cipher": shop.get("cipher") or ""},
            "config": {"shop_id": str(shop.get("id") or ""), "shop_name": shop.get("name") or "",
                       "shop_region": shop.get("region") or "", "seller_name": d.get("seller_name") or "",
                       "shops_available": ", ".join(f"{s.get('name')} ({s.get('id')})" for s in shops)},
            "account": shop.get("name") or d.get("seller_name") or ""}


def access_token(ctx: SyncContext) -> str:
    require_signed_in(ctx, "TikTok Shop")
    s = ctx.secrets
    if s.get("access_token") and int(s.get("token_expires") or 0) > time.time():
        return s["access_token"]
    if not s.get("refresh_token"):
        raise SyncError("TikTok Shop: sign-in expired. Click “Sign in” on the TikTok Shop card again.")
    key, sec = _creds(ctx.config, s)
    d = _token_call(ctx.client, "/api/v2/token/refresh", {"app_key": key, "app_secret": sec,
                                                           "refresh_token": s["refresh_token"],
                                                           "grant_type": "refresh_token"})
    save_tokens(ctx, **_token_fields(d))
    return ctx.secrets["access_token"]


# ---------------------------------------------------------------- API
def _request(client, key: str, secret: str, token: str, method: str, path: str, params: dict | None = None,
             body: dict | None = None, cipher: str = "") -> dict:
    query = {k: str(v) for k, v in (params or {}).items() if v is not None and v != ""}
    query.update({"app_key": key, "timestamp": str(int(time.time()))})
    if cipher and not path.startswith("/authorization/"):
        query["shop_cipher"] = cipher
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
    query["sign"] = sign(path, query, raw, secret)
    resp = client.request(method, f"{API}{path}", params=query, content=raw or None,
                          headers={"x-tts-access-token": token, "Content-Type": "application/json"})
    try:
        data = resp.json()
    except ValueError:
        raise SyncError(f"TikTok Shop: HTTP {resp.status_code} {resp.text[:200]}") from None
    if data.get("code") not in (0, None):
        msg = data.get("message") or "error"
        code = data.get("code")
        perm = code in PERMISSION_CODES or any(w in msg.lower() for w in PERMISSION_WORDS) or resp.status_code == 403
        hint = " Add the missing API scope to your app in Partner Center, wait for approval, then click Sign in again." if perm else ""
        raise ShopApiError(f"TikTok Shop: {msg} (code {code}).{hint}", code, perm)
    if resp.status_code >= 400:
        raise ShopApiError(f"TikTok Shop: HTTP {resp.status_code}", None, resp.status_code == 403)
    return data.get("data") or {}


def call(ctx: SyncContext, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    key, sec = _creds(ctx.config, ctx.secrets)
    return _request(ctx.client, key, sec, access_token(ctx), method, path, params, body,
                    cipher=ctx.secrets.get("shop_cipher", ""))


def test(ctx: SyncContext) -> str:
    shops = call(ctx, "GET", "/authorization/202309/shops").get("shops") or []
    names = ", ".join(s.get("name", "") for s in shops) or "no shops"
    return f"Connected to TikTok Shop: {names}"


# ---------------------------------------------------------------- orders
def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _contact_for(ctx, o: dict, name: str, email: str, phone: str) -> Contact | None:
    uid = str(o.get("user_id") or "").strip()
    if not uid:
        return None
    c = find_external(ctx.db, Contact, SOURCE, uid)
    if c is None:
        first, _, last = (name or "TikTok buyer").partition(" ")
        c = Contact(external_source=SOURCE, external_id=uid, first_name=first[:80], last_name=last[:80],
                    email=(email or "").lower()[:255], phone=(phone or "")[:60], status="customer",
                    source_channel_id=ctx.channel.id, tags="tiktok shop",
                    notes="TikTok Shop buyer. TikTok hides real emails; the address shown relays through TikTok.")
        ctx.db.add(c)
        ctx.db.flush()
        ctx.count("contacts_created")
    else:
        c.email = c.email or (email or "").lower()[:255]
        if c.status in ("lead", "prospect"):
            c.status = "customer"
    return c


def items_summary(lines: list[dict]) -> tuple[str, float]:
    """TikTok lists one line per unit; group identical SKUs back together."""
    counts = Counter((li.get("product_name") or "Item", li.get("sku_name") or "") for li in lines)
    parts = [f"{p}{f' ({s})' if s and s.lower() != 'default' else ''}{f' ×{n}' if n > 1 else ''}"
             for (p, s), n in counts.items()]
    return ", ".join(parts), float(len(lines))


def save_order(ctx: SyncContext, o: dict, funnel, stages) -> float:
    oid = str(o["id"])
    status = o.get("status") or ""
    pay = o.get("payment") or {}
    addr = o.get("recipient_address") or {}
    lines = o.get("line_items") or []
    summary, qty = items_summary(lines)
    name = addr.get("name") or " ".join(filter(None, (addr.get("first_name"), addr.get("last_name")))) or "TikTok buyer"
    email, phone = o.get("buyer_email") or "", addr.get("phone_number") or ""
    contact = _contact_for(ctx, o, name, email, phone)

    gross = _f(pay.get("total_amount"))
    canceled = status == "CANCELLED"
    kind = "lost" if canceled else ("won" if status in SHIPPED else "open")
    shipped_at = from_ts(o.get("collection_time") or o.get("rts_time")) if status in SHIPPED else None
    created, updated = from_ts(o.get("create_time")), from_ts(o.get("update_time"))

    stage = stages[kind]
    deal = find_external(ctx.db, Deal, SOURCE, oid)
    if deal is None:
        deal = Deal(external_source=SOURCE, external_id=oid, funnel_id=funnel.id, stage_id=stage.id,
                    status=stage.kind, channel_id=ctx.channel.id)
        ctx.db.add(deal)
        ctx.count("deals_created")
    else:
        ctx.count("deals_updated")
        if deal.status != stage.kind or deal.funnel_id != funnel.id:
            deal.funnel_id, deal.stage_id, deal.status = funnel.id, stage.id, stage.kind
    short = (summary[:120] + ("…" if len(summary) > 120 else "")) or "TikTok Shop sale"
    deal.title = f"TikTok Shop: {short}"[:160]
    deal.value = 0.0 if canceled else gross
    deal.closed_at = (shipped_at or updated) if kind != "open" else None
    if created:
        deal.created_at = created
    if contact:
        deal.contact_id = contact.id
    ctx.db.flush()

    order = ctx.db.scalar(select(Order).where(Order.source == SOURCE, Order.external_id == oid))
    if order is None:
        order = Order(source=SOURCE, external_id=oid, channel_id=ctx.channel.id)
        ctx.db.add(order)
        ctx.count("orders_created")
    else:
        ctx.count("orders_updated")
    order.deal_id = deal.id
    order.contact_id = contact.id if contact else order.contact_id
    order.location_id = str(o.get("warehouse_id") or "")[:60]
    order.location_name = ctx.config.get("shop_name") or "TikTok Shop"
    order.reference = oid[:120]
    order.state = "CANCELED" if canceled else ("COMPLETED" if status in SHIPPED else "OPEN")
    order.source_name = "TikTok Shop"
    order.buyer_username = str(o.get("user_id") or "")[:120]
    order.customer_name, order.customer_email, order.customer_phone = name[:200], email[:255], phone[:60]
    order.currency = (pay.get("currency") or "USD")[:3]
    order.subtotal = _f(pay.get("original_total_product_price") or pay.get("sub_total"))
    order.discount_total = round(sum(_f(pay.get(k)) for k in ("seller_discount", "platform_discount",
                                                               "shipping_fee_seller_discount",
                                                               "shipping_fee_platform_discount")), 2)
    order.tax_total = _f(pay.get("tax"))
    order.tip_total = 0.0
    order.service_charge_total = _f(pay.get("shipping_fee"))
    order.total = gross
    order.refunded = gross if canceled and o.get("paid_time") else 0.0
    order.net = 0.0 if canceled else gross
    order.processing_fee = 0.0
    order.item_count, order.items_summary = qty, summary
    order.fulfillment_type = {"FULFILLMENT_BY_SELLER": "SHIPMENT", "FULFILLMENT_BY_TIKTOK": "FBT"}.get(
        o.get("fulfillment_type") or "", o.get("fulfillment_type") or "SHIPMENT")[:40]
    order.fulfillment_state = FULFILLMENT.get(status, status)[:40]
    order.payment_summary = (o.get("payment_method_name") or "TikTok Shop")[:200]
    order.receipt_url = f"https://seller-us.tiktok.com/order/detail?order_no={oid}" \
        if (ctx.config.get("region") or "US") == "US" else f"https://seller.tiktokglobalshop.com/order/detail?order_no={oid}"
    order.ordered_at = created
    order.updated_at_ext = updated
    order.closed_at = shipped_at
    order.raw = json.dumps(o)
    tracking = {}
    for li in lines:
        tn = li.get("tracking_number") or o.get("tracking_number")
        if tn:
            tracking[tn] = {"tracking_number": tn, "provider": li.get("shipping_provider_name") or o.get("shipping_provider") or "",
                            "package_id": li.get("package_id") or ""}
    order.payments = json.dumps(list(tracking.values()))     # for TikTok Shop: tracking numbers per package
    return 0.0 if kind == "lost" else gross


def _sync_orders(ctx: SyncContext) -> None:
    funnel, stages = _funnel(ctx, FUNNEL_NAME, STAGES, "TikTok Shop")
    has_orders = ctx.db.scalar(select(Order.id).where(Order.source == SOURCE).limit(1)) is not None
    if ctx.last_sync_at and has_orders:
        body = {"update_time_ge": int((ctx.last_sync_at - timedelta(days=2)).timestamp())}
    else:
        days = max(1, min(int(ctx.config.get("history_days") or 365), 730))
        body = {"create_time_ge": int((utcnow() - timedelta(days=days)).timestamp())}
    token, total, revenue = None, 0, 0.0
    while total < MAX_ORDERS:
        data = call(ctx, "POST", "/order/202309/orders/search",
                    {"page_size": 100, "sort_field": "create_time", "sort_order": "DESC", "page_token": token}, body)
        orders = data.get("orders") or []
        for o in orders:
            total += 1
            revenue += save_order(ctx, o, funnel, stages)
        token = data.get("next_page_token")
        if not token or not orders:
            break
    ctx.stats["orders_synced"] = total
    ctx.stats["revenue_synced"] = round(revenue, 2)


def _sync_products(ctx: SyncContext) -> None:
    live, total, token, pages = 0, 0, None, 0
    while pages < 20:
        data = call(ctx, "POST", "/product/202309/products/search", {"page_size": 100, "page_token": token}, {})
        for p in data.get("products") or []:
            total += 1
            live += (p.get("status") == "ACTIVATE")
        token, pages = data.get("next_page_token"), pages + 1
        if not token:
            break
    ctx.stats["products"], ctx.stats["products_live"] = total, live
    ctx.metric("products", total, "Products", "num", "Products")
    ctx.metric("products_live", live, "Products live", "num", "Products")


# ---------------------------------------------------------------- buyer messages
def message_text(m: dict) -> str:
    kind = m.get("type") or "TEXT"
    try:
        c = json.loads(m.get("content") or "{}")
    except ValueError:
        c = {"content": m.get("content") or ""}
    if kind == "TEXT":
        return str(c.get("content") or "")
    if kind == "IMAGE":
        return f"[Photo] {c.get('url', '')}".strip()
    if kind in ("PRODUCT_CARD", "ORDER_CARD", "RETURN_REFUND_CARD", "LOGISTICS_CARD", "COUPON_CARD"):
        ref = c.get("order_id") or c.get("product_id") or c.get("coupon_id") or ""
        return f"[{kind.replace('_', ' ').title()}] {ref}".strip()
    return str(c.get("content") or c.get("text") or f"[{kind.title()}]")


def _save_messages(ctx: SyncContext, conv, msgs: list[dict]) -> None:
    for m in msgs:
        if m.get("is_visible") is False:
            continue
        sender = m.get("sender") or {}
        role = (sender.get("role") or "").upper()
        direction = "in" if role == "BUYER" else "out"
        upsert_message(ctx, conv, str(m.get("id") or f"{m.get('create_time')}-{role}"), direction=direction,
                       body=message_text(m), sent_at=from_ts(m.get("create_time")),
                       sender_name=sender.get("nickname") or role.title(), kind=m.get("type") or "TEXT", raw=m)


def _sync_messages(ctx: SyncContext, max_convs: int = 100) -> None:
    token, n = None, 0
    while n < max_convs:
        data = call(ctx, "GET", "/customer_service/202309/conversations", {"page_size": 20, "page_token": token,
                                                                           "locale": "en"})
        convs = data.get("conversations") or []
        for c in convs:
            n += 1
            buyer = next((p for p in c.get("participants") or [] if (p.get("role") or "").upper() == "BUYER"),
                         (c.get("participants") or [{}])[0])
            contact = find_external(ctx.db, Contact, SOURCE, str(buyer.get("user_id"))) if buyer.get("user_id") else None
            conv = upsert_conversation(
                ctx, SOURCE, str(c["id"]), title=(buyer.get("nickname") or (f"{contact.first_name} {contact.last_name}".strip() if contact else "") or "TikTok Shop buyer")[:200],
                avatar_url=buyer.get("avatar") or "", peer_id=str(buyer.get("user_id") or buyer.get("im_user_id") or ""),
                unread=int(c.get("unread_count") or 0), can_reply=c.get("can_send_message", True) is not False,
                reply_note="" if c.get("can_send_message", True) is not False else "TikTok Shop closed replies for this chat.",
                contact_id=contact.id if contact else None)
            latest = c.get("latest_message") or {}
            newest_known = conv.last_message_at
            latest_at = from_ts(latest.get("create_time"))
            if latest_at is None or newest_known is None or latest_at > newest_known or not conv.messages:
                msgs = call(ctx, "GET", f"/customer_service/202309/conversations/{c['id']}/messages",
                            {"page_size": 10, "sort_order": "DESC", "locale": "en"}).get("messages") or []
                _save_messages(ctx, conv, msgs)
            ctx.db.flush()
            ctx.db.refresh(conv)
            refresh_summary(conv)
        token = data.get("next_page_token")
        if not token or not convs:
            break
    ctx.stats["conversations"] = n


def load_older(ctx: SyncContext, conv, pages: int = 5) -> None:
    """Fetch the full history of one chat (newest first, 10 per page)."""
    token = None
    for _ in range(pages):
        data = call(ctx, "GET", f"/customer_service/202309/conversations/{conv.external_id}/messages",
                    {"page_size": 10, "sort_order": "DESC", "page_token": token, "locale": "en"})
        _save_messages(ctx, conv, data.get("messages") or [])
        token = data.get("next_page_token")
        if not token:
            break


def send_message(ctx: SyncContext, conv, text: str) -> str:
    data = call(ctx, "POST", f"/customer_service/202309/conversations/{conv.external_id}/messages", None,
                {"type": "TEXT", "content": json.dumps({"content": text[:2000]})})
    try:
        call(ctx, "POST", f"/customer_service/202309/conversations/{conv.external_id}/messages/read", None, {})
    except SyncError:
        pass
    return str(data.get("message_id") or "")


# ---------------------------------------------------------------- shipping
def shipping_providers(ctx: SyncContext, order: Order) -> list[dict]:
    raw = json.loads(order.raw or "{}")
    opt = raw.get("delivery_option_id")
    if not opt:
        raise SyncError("TikTok Shop didn't say which delivery option this order uses")
    data = call(ctx, "GET", f"/logistics/202309/delivery_options/{opt}/shipping_providers")
    return [{"id": str(p.get("id")), "name": p.get("name") or ""} for p in data.get("shipping_providers") or []]


def mark_shipped(ctx: SyncContext, order: Order, tracking_number: str, provider_id: str) -> dict:
    raw = json.loads(order.raw or "{}")
    if raw.get("shipping_type") == "TIKTOK":
        raise SyncError("This order ships with a TikTok shipping label. Buy and print the label in TikTok Seller Center.")
    lines = [str(li["id"]) for li in raw.get("line_items") or [] if li.get("id") and not li.get("tracking_number")]
    body = {"tracking_number": tracking_number.strip(), "shipping_provider_id": provider_id}
    if lines:
        body["order_line_item_ids"] = lines
    return call(ctx, "POST", f"/fulfillment/202309/orders/{order.external_id}/packages", None, body)


# ---------------------------------------------------------------- buyer-message status
WAITING_RECHECK_MINUTES = 60          # while TikTok hasn't approved Customer Service, look again hourly
ERROR_RECHECK_MINUTES = 15


def messages_every(config: dict) -> int:
    try:
        return max(0, min(int(str(config.get("messages_every_minutes") or "5").strip()), 1440))
    except ValueError:
        return 5


def set_messages_status(db, integration_id: int | None, status: str, error: str = "") -> None:
    """Remember whether buyer chats work: active | waiting_approval | error | not_signed_in (no commit)."""
    from ..models import Integration
    integ = db.get(Integration, integration_id) if integration_id else None
    if integ is None:
        return
    cfg = json.loads(integ.config or "{}")
    if cfg.get("messages_status") == "waiting_approval" and status == "active":
        cfg["messages_activated_at"] = utcnow().isoformat()
    cfg.update(messages_status=status, messages_error=error[:500], messages_checked_at=utcnow().isoformat())
    integ.config = json.dumps(cfg)


def _messages_step(ctx: SyncContext) -> None:
    try:
        _sync_messages(ctx)
    except SyncError as e:
        if is_permission_error(e):
            set_messages_status(ctx.db, ctx.integration_id, "waiting_approval", str(e))
            ctx.warnings.append("Buyer messages are waiting for TikTok to approve the Customer service permission. "
                                "Once it's approved, click Sign in on this connection again. The Messages page shows the steps.")
        else:
            set_messages_status(ctx.db, ctx.integration_id, "error", str(e))
            ctx.warnings.append(f"Buyer messages unavailable ({e}).")
        return
    set_messages_status(ctx.db, ctx.integration_id, "active")


def check_messages(db, integ) -> dict:
    """Pull only buyer chats (used by the frequent background check and the "Check now" button)."""
    from . import base
    from .crypto import decrypt_secrets
    from .service import _context, _lock
    lock = _lock(integ.id)
    if not lock.acquire(blocking=False):
        return {"skipped": "A sync is already running"}
    try:
        try:
            secrets = decrypt_secrets(integ.secrets)
        except ValueError:
            secrets = {}
        if not (secrets.get("refresh_token") or secrets.get("access_token")):
            set_messages_status(db, integ.id, "not_signed_in")
            db.commit()
            return {"status": "not_signed_in"}
        with base.make_client() as client:
            ctx = _context(db, integ, client)
            _messages_step(ctx)
        db.commit()
        cfg = json.loads(db.get(type(integ), integ.id).config or "{}")
        return {"status": cfg.get("messages_status"), "error": cfg.get("messages_error", ""),
                "conversations": ctx.stats.get("conversations", 0), "new_messages": ctx.stats.get("messages_synced", 0)}
    except Exception as e:  # noqa: BLE001 - keep the background loop alive; record what went wrong
        db.rollback()
        set_messages_status(db, integ.id, "error", str(e))
        db.commit()
        return {"status": "error", "error": str(e)}
    finally:
        lock.release()


def message_check_due(config: dict, now) -> bool:
    from datetime import datetime
    status = config.get("messages_status") or ""
    every = messages_every(config)
    if status == "waiting_approval":
        every = WAITING_RECHECK_MINUTES
    elif status == "error":
        every = max(every, ERROR_RECHECK_MINUTES) if every else 0
    elif status == "not_signed_in":
        return False
    if not every:
        return False
    last = config.get("messages_checked_at")
    if not last:
        return True
    try:
        return datetime.fromisoformat(last) + timedelta(minutes=every) <= now
    except ValueError:
        return True


# ---------------------------------------------------------------- sync
def sync(ctx: SyncContext) -> None:
    if ctx.config.get("shop_name"):
        ctx.channel.name = ctx.channel.name or ctx.config["shop_name"]
    _sync_orders(ctx)
    try:
        _sync_products(ctx)
    except SyncError as e:
        ctx.warnings.append(f"Products unavailable ({e}).")
    _messages_step(ctx)

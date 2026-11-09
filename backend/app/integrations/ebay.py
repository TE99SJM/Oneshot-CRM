"""eBay: every sold order (Fulfillment API) -> Orders tab, buyers -> Contacts, orders -> deals in an "eBay Sales" funnel.

Auth is eBay's OAuth authorization-code flow.  The seller signs in once on eBay; the CRM trades the
one-time code for an 18-month refresh token and mints a fresh 2-hour access token on every sync.
"""
import base64
import hashlib
import hmac
import json
import secrets as _secrets
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from sqlalchemy import select

from ..config import settings
from ..models import Contact, Deal, Order, utcnow
from .base import FAST_INTERVAL, FieldSpec, ProviderInfo, SyncContext, SyncError, find_external, parse_dt
from .square import _funnel

FUNNEL_NAME = "eBay Sales"
STAGES = ("Needs shipping", "Shipped", "Refunded / canceled")
SCOPES = ["https://api.ebay.com/oauth/api_scope", "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"]
ANALYTICS_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly"
AUTH_SCOPES = SCOPES + [ANALYTICS_SCOPE]      # asked for at sign-in; syncing still works with the older two
MAX_ORDERS = 5000
MAX_TRACKING_LOOKUPS = 400        # per sync; tracking for older orders is kept from previous syncs

INFO = ProviderInfo(
    key="ebay", name="eBay", platform="ebay", channel_kind="marketplace",
    summary="Every eBay sale with buyer, items, shipping, tracking, fees and refunds.",
    syncs=["Every sold order with full details → Orders tab", "Buyers → Contacts",
           "Orders → deals in an eBay Sales funnel (needs shipping / shipped / refunded)",
           "eBay fees, refunds, ship-to address and tracking numbers"],
    fields=[
        FieldSpec("client_id", "App ID (Client ID)", placeholder="YourName-OneshotC-PRD-…",
                  help="Production keyset → App ID on developer.ebay.com → Application Keys."),
        FieldSpec("client_secret", "Cert ID (Client Secret)", secret=True, placeholder="PRD-…",
                  help="Production keyset → Cert ID. Treat it like a password."),
        FieldSpec("ru_name", "RuName (eBay Redirect URL name)", placeholder="Your_Name-YourName-Onesho-abcdefg", required=False,
                  help="You can add this later, after eBay turns your keys on. "
                       "User Tokens → “Get a Token from eBay via Your Application” → the RuName shown there."),
        FieldSpec("environment", "Environment", kind="select", options=["production", "sandbox"], default="production",
                  required=False, help="Use sandbox only with sandbox keys."),
        FieldSpec("history_days", "Days of order history on first sync", required=False, default="365", placeholder="365",
                  help="eBay keeps up to 2 years (730 days)."),
        FieldSpec("deletion_endpoint", "Account-deletion notice URL", required=False,
                  placeholder="https://your-server.your-tailnet.ts.net/api/ebay/account-deletion",
                  help="The public https address you give eBay for account-deletion notices (see the steps)."),
    ],
    steps=[
        "Go to developer.ebay.com and sign in with your eBay seller account (joining the Developers Program is free).",
        "Open Hi <name> → Application Keys, name the app “Oneshot CRM” and click Create a keyset under Production.",
        "Copy the Production App ID and Cert ID into this form and click Save. You can leave RuName empty for now.",
        "The CRM then opens “eBay setup”. Part 1 gives you the URL and verification token eBay asks for on its "
        "Marketplace Account Deletion page. Once eBay accepts them, your keys switch on.",
        "Part 2: on eBay click User Tokens → “Get a Token from eBay via Your Application” → Add eBay Redirect URL, "
        "fill in a privacy policy URL, tick OAuth, Save, and copy the RuName into the CRM.",
        "Part 3: click “Open eBay sign-in”, click Agree, then copy the address of the page you land on and paste it into the CRM.",
    ],
    docs_url="https://developer.ebay.com/develop/guides/sell/get-started-with-ebay-apis",
    default_interval=FAST_INTERVAL,
)


# ----------------------------------------------------------------------------------------------- OAuth helpers
def _hosts(config: dict) -> tuple[str, str]:
    if config.get("environment") == "sandbox":
        return "https://auth.sandbox.ebay.com", "https://api.sandbox.ebay.com"
    return "https://auth.ebay.com", "https://api.ebay.com"


def _state_sig(integration_id: int) -> str:
    return hmac.new(f"ebay-state:{settings.secret_key}".encode(), str(integration_id).encode(), hashlib.sha256).hexdigest()[:24]


def make_state(integration_id: int) -> str:
    return f"{integration_id}.{_state_sig(integration_id)}"


def read_state(state: str) -> int | None:
    iid, _, sig = (state or "").partition(".")
    if iid.isdigit() and hmac.compare_digest(sig, _state_sig(int(iid))):
        return int(iid)
    return None


def authorize_url(integration_id: int, config: dict) -> str:
    if not config.get("client_id") or not config.get("ru_name"):
        raise SyncError("eBay: save the App ID and RuName first")
    auth, _ = _hosts(config)
    q = urlencode({"client_id": config["client_id"], "response_type": "code", "redirect_uri": config["ru_name"],
                   "scope": " ".join(AUTH_SCOPES), "state": make_state(integration_id), "prompt": "login"})
    return f"{auth}/oauth2/authorize?{q}"


def extract_code(pasted: str) -> str:
    """Accept the full address eBay lands on, just its query string, or the bare code."""
    v = (pasted or "").strip().strip('"').strip("'")
    if not v:
        raise SyncError("eBay: paste the address of the page eBay sent you to")
    if "code=" in v:
        qs = urlparse(v).query if "://" in v else v.split("?", 1)[-1]
        code = (parse_qs(qs).get("code") or [""])[0]
        if code:
            return code
    if "isAuthSuccessful=false" in v:
        raise SyncError("eBay: the sign-in was declined. Try again and click “Agree”.")
    if v.startswith("v^") or v.startswith("v%5E"):
        return unquote(v)
    raise SyncError("eBay: couldn't find the sign-in code in what you pasted. Copy the whole address bar from the "
                    "page eBay shows after you click Agree (it contains “code=”). Codes expire after 5 minutes.")


def _basic(config: dict, secrets: dict) -> str:
    cid, sec = config.get("client_id", "").strip(), secrets.get("client_secret", "").strip()
    if not cid or not sec:
        raise SyncError("eBay: enter the App ID and Cert ID")
    return "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode()


def _token_call(client, config: dict, secrets: dict, data: dict) -> dict:
    _, api = _hosts(config)
    r = client.post(f"{api}/identity/v1/oauth2/token", data=data,
                    headers={"Authorization": _basic(config, secrets), "Content-Type": "application/x-www-form-urlencoded"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        err, desc = body.get("error", ""), body.get("error_description", "") or r.text[:200]
        if err == "invalid_client":
            raise SyncError("eBay: the App ID or Cert ID was rejected. Check you copied the Production keys.")
        if err == "invalid_grant":
            raise SyncError(f"eBay: sign-in expired or was already used ({desc}). Click “Sign in with eBay” again.")
        raise SyncError(f"eBay: token request failed ({err or r.status_code}: {desc})")
    return body


def exchange_code(client, config: dict, secrets: dict, code: str) -> dict:
    """One-time code -> {"refresh_token", "refresh_token_expires_in", "access_token", ...}."""
    if not config.get("ru_name"):
        raise SyncError("eBay: save the RuName first")
    body = _token_call(client, config, secrets, {"grant_type": "authorization_code", "code": code,
                                                 "redirect_uri": config["ru_name"]})
    if not body.get("refresh_token"):
        raise SyncError("eBay: eBay didn't return a refresh token")
    return body


def _access_token(ctx: SyncContext) -> str:
    rt = ctx.secrets.get("refresh_token", "").strip()
    if not rt:
        raise SyncError("eBay: not signed in yet. Click “Sign in with eBay” on this connection.")
    return _token_call(ctx.client, ctx.config, ctx.secrets,
                       {"grant_type": "refresh_token", "refresh_token": rt, "scope": " ".join(SCOPES)})["access_token"]


# ----------------------------------------------------------------------------------------------- account deletion
def new_verification_token() -> str:
    return "oneshot-" + _secrets.token_urlsafe(30).replace("_", "-")[:40]


def challenge_response(challenge_code: str, verification_token: str, endpoint: str) -> str:
    return hashlib.sha256((challenge_code + verification_token + endpoint).encode()).hexdigest()


def delete_buyer_data(db, username: str) -> int:
    """Remove a closed eBay account's personal data (orders, deals and the synced contact)."""
    if not username:
        return 0
    n = 0
    for o in db.scalars(select(Order).where(Order.source == "ebay", Order.buyer_username == username)).all():
        deal = find_external(db, Deal, "ebay", o.external_id)
        if deal:
            db.delete(deal)
        db.delete(o)
        n += 1
    c = find_external(db, Contact, "ebay", username)
    if c:
        db.delete(c)
        n += 1
    db.commit()
    return n


def _pem(key: str) -> bytes:
    body = key.replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "").replace("\n", "").strip()
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return ("-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n").encode()


def verify_notification(client, config: dict, secrets: dict, body: bytes, signature_header: str) -> bool | None:
    """True = signed by eBay, False = forged, None = couldn't check (missing header/keys/network)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        sig = json.loads(base64.b64decode(signature_header))
        tok = _token_call(client, config, secrets, {"grant_type": "client_credentials", "scope": SCOPES[0]})["access_token"]
        _, api = _hosts(config)
        r = client.get(f"{api}/commerce/notification/v1/public_key/{sig['kid']}", headers={"Authorization": f"Bearer {tok}"})
        r.raise_for_status()
        key = serialization.load_pem_public_key(_pem(r.json()["key"]))
    except Exception:
        return None
    try:
        key.verify(base64.b64decode(sig["signature"]), body, ec.ECDSA(hashes.SHA1()))
        return True
    except InvalidSignature:
        return False
    except Exception:
        return None


# ----------------------------------------------------------------------------------------------- API calls
def _api_get(ctx: SyncContext, token: str, path: str, **params) -> dict:
    _, api = _hosts(ctx.config)
    r = ctx.client.get(f"{api}{path}", params=params,
                       headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
    if r.status_code >= 400:
        try:
            errs = r.json().get("errors") or []
            detail = "; ".join(e.get("longMessage") or e.get("message", "") for e in errs)
        except ValueError:
            detail = r.text[:200]
        hint = {401: "access was rejected (sign in with eBay again)", 403: "access denied (the keyset may be "
                "disabled until you finish the account-deletion step on developer.ebay.com)",
                429: "eBay's daily call limit reached, try again later"}.get(r.status_code, f"HTTP {r.status_code}")
        raise SyncError(f"eBay: {hint}{' - ' + detail if detail else ''}")
    return r.json()


def test(ctx: SyncContext) -> str:
    token = _access_token(ctx)
    data = _api_get(ctx, token, "/sell/fulfillment/v1/order", limit=1)
    return f"Connected to eBay ({data.get('total', 0)} orders in the last 90 days)"


def _amt(a) -> float:
    try:
        return round(float((a or {}).get("value") or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _ship_to(o) -> dict:
    for fi in o.get("fulfillmentStartInstructions") or []:
        st = (fi.get("shippingStep") or {}).get("shipTo")
        if st:
            return st
    return {}


def _contact_for(ctx, o, name: str, email: str, phone: str) -> Contact | None:
    username = ((o.get("buyer") or {}).get("username") or "").strip()
    if not username:
        return None
    c = find_external(ctx.db, Contact, "ebay", username)
    if c is None:
        first, _, last = (name or username).partition(" ")
        c = Contact(external_source="ebay", external_id=username, first_name=first[:80] or username[:80],
                    last_name=last[:80], email=(email or "").lower(), phone=phone or "", status="customer",
                    source_channel_id=ctx.channel.id, tags="ebay", notes=f"eBay buyer: {username}")
        ctx.db.add(c)
        ctx.db.flush()
        ctx.count("contacts_created")
    else:
        c.email = c.email or (email or "").lower()
        c.phone = c.phone or phone or ""
        if c.status in ("lead", "prospect"):
            c.status = "customer"
    return c


def _save_order(ctx, o, tracking: list[dict] | None, funnel, stages) -> float:
    order = ctx.db.scalar(select(Order).where(Order.source == "ebay", Order.external_id == o["orderId"]))
    if tracking is None:
        tracking = json.loads(order.payments or "[]") if order else []
    ps = o.get("pricingSummary") or {}
    pay = o.get("paymentSummary") or {}
    gross = _amt(ps.get("total"))
    refunded = round(sum(_amt(r.get("amount")) for r in pay.get("refunds") or []
                         if (r.get("refundStatus") or "REFUNDED") == "REFUNDED"), 2)
    if not refunded:
        refunded = round(sum(_amt(r.get("amount")) for li in o.get("lineItems") or [] for r in li.get("refunds") or []), 2)
    net = round(max(gross - refunded, 0.0), 2)
    items = o.get("lineItems") or []
    def _label(li):
        aspects = " / ".join(a.get("value", "") for a in li.get("variationAspects") or [] if a.get("value"))
        q = li.get("quantity") or 1
        return f"{li.get('title') or 'Item'}{' (' + aspects + ')' if aspects else ''}{f' ×{q}' if q != 1 else ''}"
    summary = ", ".join(_label(li) for li in items)
    qty = float(sum(int(li.get("quantity") or 0) for li in items))
    buyer = o.get("buyer") or {}
    reg = buyer.get("buyerRegistrationAddress") or {}
    ship = _ship_to(o)
    name = ship.get("fullName") or reg.get("fullName") or buyer.get("username", "")
    email = reg.get("email") or ship.get("email") or ""
    phone = ((ship.get("primaryPhone") or reg.get("primaryPhone") or {}).get("phoneNumber") or "")
    contact = _contact_for(ctx, o, name, email, phone)

    canceled = (o.get("cancelStatus") or {}).get("cancelState") == "CANCELED"
    pay_status = o.get("orderPaymentStatus", "")
    ful_status = o.get("orderFulfillmentStatus", "")
    state = "CANCELED" if canceled else ("COMPLETED" if ful_status == "FULFILLED" else "OPEN")
    fully_refunded = pay_status == "FULLY_REFUNDED" or (gross > 0 and refunded >= gross)
    kind = "lost" if canceled or fully_refunded else ("won" if ful_status == "FULFILLED" else "open")
    shipped = sorted(filter(None, (parse_dt(t.get("shippedDate")) for t in tracking)))

    stage = stages[kind]
    deal = find_external(ctx.db, Deal, "ebay", o["orderId"])
    if deal is None:
        deal = Deal(external_source="ebay", external_id=o["orderId"], funnel_id=funnel.id, stage_id=stage.id,
                    status=stage.kind, channel_id=ctx.channel.id)
        ctx.db.add(deal)
        ctx.count("deals_created")
    else:
        ctx.count("deals_updated")
        if deal.status != stage.kind or deal.funnel_id != funnel.id:
            deal.funnel_id, deal.stage_id, deal.status = funnel.id, stage.id, stage.kind
    short = (summary[:120] + ("…" if len(summary) > 120 else "")) or "eBay sale"
    deal.title = f"eBay: {short}"[:160]
    deal.value = net
    created = parse_dt(o.get("creationDate"))
    deal.closed_at = (shipped[-1] if shipped else parse_dt(o.get("lastModifiedDate"))) if kind != "open" else None
    if created:
        deal.created_at = created
    if contact:
        deal.contact_id = contact.id
    ctx.db.flush()

    if order is None:
        order = Order(source="ebay", external_id=o["orderId"], channel_id=ctx.channel.id)
        ctx.db.add(order)
        ctx.count("orders_created")
    else:
        ctx.count("orders_updated")
    order.deal_id, order.contact_id = deal.id, contact.id if contact else order.contact_id
    order.location_id = (items[0].get("listingMarketplaceId") if items else "") or ""
    order.location_name = order.location_id.replace("EBAY_", "eBay ") if order.location_id else ""
    order.reference = str(o.get("salesRecordReference") or o["orderId"])[:120]
    order.state = state
    order.source_name = "eBay"
    order.buyer_username = (buyer.get("username") or "")[:120]
    order.customer_name, order.customer_email, order.customer_phone = name[:200], email[:255], phone[:60]
    order.currency = (ps.get("total") or {}).get("currency", "USD")
    order.subtotal = _amt(ps.get("priceSubtotal"))
    order.discount_total = round(abs(_amt(ps.get("priceDiscount"))) + abs(_amt(ps.get("deliveryDiscount"))), 2)
    order.tax_total = _amt(ps.get("tax"))
    order.tip_total = 0.0
    order.service_charge_total = _amt(ps.get("deliveryCost"))        # shipping charged to the buyer
    order.total, order.refunded, order.net = gross, refunded, net
    order.processing_fee = abs(_amt(o.get("totalMarketplaceFee")))
    order.item_count, order.items_summary = qty, summary
    fis = o.get("fulfillmentStartInstructions") or [{}]
    ftype = (fis[0].get("fulfillmentInstructionsType") or "")
    order.fulfillment_type = {"SHIP_TO": "SHIPMENT", "DIGITAL": "DIGITAL", "PREPARE_FOR_PICKUP": "PICKUP",
                              "FULFILLED_BY_EBAY": "SHIPMENT"}.get(ftype, ftype)[:40]
    order.fulfillment_state = {"NOT_STARTED": "NEEDS_SHIPPING", "IN_PROGRESS": "PARTLY_SHIPPED",
                               "FULFILLED": "SHIPPED"}.get(ful_status, ful_status)[:40]
    methods = {p.get("paymentMethod") for p in pay.get("payments") or [] if p.get("paymentMethod")}
    order.payment_summary = (", ".join(sorted(m.replace("_", " ").title() for m in methods)) or "eBay")[:200]
    if order.payment_summary == "Ebay":
        order.payment_summary = "eBay managed payments"
    order.receipt_url = f"https://www.ebay.com/sh/ord/details?orderid={o['orderId']}"
    order.ordered_at = created
    order.updated_at_ext = parse_dt(o.get("lastModifiedDate"))
    order.closed_at = shipped[-1] if shipped else None
    order.raw = json.dumps(o)
    order.payments = json.dumps(tracking)              # for eBay: shipping fulfillments (tracking numbers)
    return 0.0 if kind == "lost" else net


def sync(ctx: SyncContext) -> None:
    token = _access_token(ctx)
    funnel, stages = _funnel(ctx, FUNNEL_NAME, STAGES, "eBay")
    days = max(1, min(int(ctx.config.get("history_days") or 365), 730))
    has_orders = ctx.db.scalar(select(Order.id).where(Order.source == "ebay").limit(1)) is not None
    if ctx.last_sync_at and has_orders:
        flt = f"lastmodifieddate:[{(ctx.last_sync_at - timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%S.000Z')}..]"
    else:
        flt = f"creationdate:[{(utcnow() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S.000Z')}..]"
    offset, total, revenue, lookups = 0, 0, 0.0, 0
    while total < MAX_ORDERS:
        data = _api_get(ctx, token, "/sell/fulfillment/v1/order", filter=flt, limit=200, offset=offset)
        orders = data.get("orders") or []
        for o in orders:
            total += 1
            tracking = None
            if o.get("orderFulfillmentStatus") in ("IN_PROGRESS", "FULFILLED") and lookups < MAX_TRACKING_LOOKUPS:
                lookups += 1
                try:
                    tracking = _api_get(ctx, token, f"/sell/fulfillment/v1/order/{o['orderId']}/shipping_fulfillment"
                                        ).get("fulfillments") or []
                except SyncError as e:
                    if lookups == 1:
                        ctx.warnings.append(f"Tracking numbers unavailable ({e}).")
            revenue += _save_order(ctx, o, tracking, funnel, stages)
        if not data.get("next") or not orders:
            break
        offset += len(orders)
    # Catch up tracking for shipped orders we couldn't look up in earlier syncs.
    ctx.db.flush()
    if lookups < MAX_TRACKING_LOOKUPS:
        missing = ctx.db.scalars(select(Order).where(Order.source == "ebay", Order.payments == "[]",
                                                     Order.fulfillment_state.in_(("SHIPPED", "PARTLY_SHIPPED")))
                                 .limit(MAX_TRACKING_LOOKUPS - lookups)).all()
        for order in missing:
            lookups += 1
            try:
                tr = _api_get(ctx, token, f"/sell/fulfillment/v1/order/{order.external_id}/shipping_fulfillment"
                              ).get("fulfillments") or []
            except SyncError:
                break
            order.payments = json.dumps(tr)
            dates = sorted(filter(None, (parse_dt(t.get("shippedDate")) for t in tr)))
            order.closed_at = dates[-1] if dates else order.closed_at
    if lookups >= MAX_TRACKING_LOOKUPS:
        ctx.warnings.append("Tracking for some older orders will fill in on the next syncs.")
    ctx.stats["orders_synced"] = total
    ctx.stats["revenue_synced"] = round(revenue, 2)
    _listing_counts(ctx, token)
    _traffic(ctx)


TRAFFIC = [  # eBay metric: (key, label, section)
    ("LISTING_IMPRESSION_TOTAL", "ebay_impressions_30d", "Listing impressions", "Traffic"),
    ("LISTING_IMPRESSION_SEARCH_RESULTS_PAGE", "ebay_search_impressions_30d", "Impressions in search results", "Traffic"),
    ("LISTING_IMPRESSION_STORE", "ebay_store_impressions_30d", "Impressions in your eBay Store", "Traffic"),
    ("LISTING_VIEWS_TOTAL", "ebay_views_30d", "Listing page views", "Traffic"),
    ("LISTING_VIEWS_SOURCE_DIRECT", "ebay_views_direct_30d", "Page views: direct", "Traffic"),
    ("LISTING_VIEWS_SOURCE_OFF_EBAY", "ebay_views_off_ebay_30d", "Page views from outside eBay", "Traffic"),
    ("LISTING_VIEWS_SOURCE_SEARCH_RESULTS_PAGE", "ebay_views_search_30d", "Page views from search", "Traffic"),
    ("TRANSACTION", "ebay_transactions_30d", "Transactions (items sold)", "Sales"),
]


def _traffic(ctx: SyncContext) -> None:
    """Impressions, listing views and conversion (Sell Analytics, last 30 days). Needs the sign-in to include
    sell.analytics.readonly - connections signed in before this version need one more “Sign in with eBay”."""
    rt = ctx.secrets.get("refresh_token", "").strip()
    try:
        tok = _token_call(ctx.client, ctx.config, ctx.secrets, {"grant_type": "refresh_token", "refresh_token": rt,
                                                                 "scope": " ".join([SCOPES[0], ANALYTICS_SCOPE])})["access_token"]
    except SyncError:
        ctx.warnings.append("For eBay impressions, page views and conversion rate, click “Sign in with eBay” once more "
                            "(it adds the analytics permission).")
        return
    end = utcnow().date() - timedelta(days=1)
    start = end - timedelta(days=29)
    try:
        data = _api_get(ctx, tok, "/sell/analytics/v1/traffic_report", dimension="DAY",
                        metric=",".join(m[0] for m in TRAFFIC),
                        filter=f"marketplace_ids:{{EBAY_US}},date_range:[{start:%Y%m%d}..{end:%Y%m%d}]")
    except SyncError as e:
        ctx.warnings.append(f"eBay traffic report unavailable ({e}).")
        return
    keys = [h.get("key") for h in (data.get("header") or {}).get("metrics") or []]
    totals = dict.fromkeys(keys, 0.0)
    for rec in data.get("records") or []:
        for k, mv in zip(keys, rec.get("metricValues") or []):
            try:
                totals[k] += float(mv.get("value") or 0)
            except (TypeError, ValueError):
                pass
    for api_name, key, label, section in TRAFFIC:
        if api_name in totals:
            ctx.metric(key, totals[api_name], label, "num", section, "30d")
    imp, views, tx = (totals.get("LISTING_IMPRESSION_TOTAL"), totals.get("LISTING_VIEWS_TOTAL"),
                      totals.get("TRANSACTION"))
    if imp:
        ctx.metric("ebay_ctr_30d", round((views or 0) / imp * 100, 2), "Views per impression (click-through)", "pct",
                   "Traffic", "30d", "avg")
    if views:
        ctx.metric("ebay_conversion_30d", round((tx or 0) / views * 100, 2), "Sales conversion rate", "pct",
                   "Traffic", "30d", "avg")


def _listing_counts(ctx: SyncContext, token: str) -> None:
    """Active / sold / unsold listing counts from the Trading API (GetMyeBaySelling)."""
    import re
    _, api = _hosts(ctx.config)
    xml = ('<?xml version="1.0" encoding="utf-8"?><GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
           + "".join(f"<{n}><Include>true</Include><Pagination><EntriesPerPage>1</EntriesPerPage></Pagination></{n}>"
                     for n in ("ActiveList", "SoldList", "UnsoldList"))
           + "<DetailLevel>ReturnSummary</DetailLevel></GetMyeBaySellingRequest>")
    try:
        r = ctx.client.post(f"{api}/ws/api.dll", content=xml.encode(), headers={
            "X-EBAY-API-CALL-NAME": "GetMyeBaySelling", "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1193", "X-EBAY-API-IAF-TOKEN": token, "Content-Type": "text/xml"})
    except Exception as e:  # network
        ctx.warnings.append(f"Listing counts unavailable ({type(e).__name__}).")
        return
    body = r.text if r.status_code < 400 else ""
    if "<Ack>Failure</Ack>" in body or not body:
        ctx.warnings.append("Listing counts unavailable (eBay Trading API refused the request).")
        return

    def total(section: str):
        m = re.search(rf"<{section}>.*?<TotalNumberOfEntries>(\d+)</TotalNumberOfEntries>", body, re.S)
        return int(m.group(1)) if m else None
    ctx.metric("ebay_active_listings", total("ActiveList"), "Active listings", "num", "Listings")
    ctx.metric("ebay_sold_listings_60d", total("SoldList"), "Sold listings", "num", "Listings", "60d")
    ctx.metric("ebay_unsold_listings_60d", total("UnsoldList"), "Ended without selling", "num", "Listings", "60d")
    m = re.search(r"<Summary>.*?<TotalAuctionSellingValue[^>]*>([\d.]+)<", body, re.S)
    if m:
        ctx.metric("ebay_auction_value", float(m.group(1)), "Current auction value", "money", "Listings")

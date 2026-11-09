"""Square: customers -> Contacts, completed orders -> won Deals in a "Square Sales" funnel."""
from datetime import timedelta

from sqlalchemy import select

import json

from ..models import Contact, Deal, Funnel, FunnelStage, Order, utcnow
from .base import FAST_INTERVAL, FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, find_external, parse_dt

SQUARE_VERSION = "2026-09-16"
FUNNEL_NAME = "Square Sales"
MAX_CUSTOMERS = 5000
MAX_ORDERS = 5000

INFO = ProviderInfo(
    key="square", name="Square", platform="square", channel_kind="direct",
    summary="Your Square customers become contacts and completed orders become won deals.",
    syncs=["Every order with full details → Orders tab", "Customers → Contacts", "Orders → deals in a Square Sales funnel (paid = won, open = in progress)", "Payments, fees, refunds, fulfillment and shipping info"],
    fields=[
        FieldSpec("access_token", "Access token", secret=True, placeholder="EAAA...",
                  help="Production access token from the Square Developer Console."),
        FieldSpec("environment", "Environment", kind="select", options=["production", "sandbox"], default="production",
                  required=False, help="Use sandbox only with a sandbox test token."),
        FieldSpec("history_days", "Days of order history on first sync", required=False, default="365", placeholder="365"),
    ],
    steps=[
        "Go to developer.squareup.com and sign in with your Square seller account.",
        "Click “Create an application” (or “+”), name it “Oneshot CRM” and finish the short setup.",
        "Open the app, switch the toggle at the top from Sandbox to Production, and go to Credentials.",
        "Copy the Production Access token (click Show). Treat it like a password.",
        "Paste it here and leave Environment on production.",
    ],
    docs_url="https://developer.squareup.com/docs/build-basics/access-tokens",
    default_interval=FAST_INTERVAL,
)


def _base(ctx: SyncContext) -> str:
    return ("https://connect.squareupsandbox.com" if ctx.config.get("environment") == "sandbox"
            else "https://connect.squareup.com")


def _headers(ctx: SyncContext) -> dict:
    token = ctx.secrets.get("access_token", "").strip()
    if not token:
        raise SyncError("Square: enter an access token")
    return {"Authorization": f"Bearer {token}", "Square-Version": SQUARE_VERSION, "Content-Type": "application/json"}


def _get(ctx, path, **params):
    return check_response(ctx.client.get(f"{_base(ctx)}{path}", headers=_headers(ctx), params=params), "Square")


def _post(ctx, path, body):
    return check_response(ctx.client.post(f"{_base(ctx)}{path}", headers=_headers(ctx), json=body), "Square")


def _locations(ctx) -> list[dict]:
    return [loc for loc in _get(ctx, "/v2/locations").get("locations", []) if loc.get("status", "ACTIVE") == "ACTIVE"]


def test(ctx: SyncContext) -> str:
    locs = _locations(ctx)
    names = ", ".join(loc.get("name", "?") for loc in locs[:3]) or "no active locations"
    return f"Connected to Square ({len(locs)} location{'s' if len(locs) != 1 else ''}: {names})"


def _funnel(ctx, name: str = FUNNEL_NAME, labels: tuple[str, str, str] = ("Open order", "Paid", "Refunded / canceled"),
            source: str = "Square") -> tuple[Funnel, dict[str, FunnelStage]]:
    """Find or create an auto-managed sales funnel with open/won/lost stages (shared with eBay)."""
    funnel = ctx.db.scalar(select(Funnel).where(Funnel.name == name))
    if funnel is None:
        funnel = Funnel(name=name, description=f"Created automatically from {source} orders.")
        funnel.stages = [FunnelStage(name=labels[0], position=0, probability=50, kind="open"),
                         FunnelStage(name=labels[1], position=1, probability=100, kind="won"),
                         FunnelStage(name=labels[2], position=2, probability=0, kind="lost")]
        ctx.db.add(funnel)
        ctx.db.flush()
    by_kind: dict[str, FunnelStage] = {}
    for st in sorted(funnel.stages, key=lambda s: s.position):
        by_kind.setdefault(st.kind, st)
    for kind, stage_name in zip(("open", "won", "lost"), labels):
        if kind not in by_kind:   # user deleted a stage: recreate it
            st = FunnelStage(funnel_id=funnel.id, name=stage_name, position=len(funnel.stages), kind=kind,
                             probability={"open": 50, "won": 100, "lost": 0}[kind])
            ctx.db.add(st)
            funnel.stages.append(st)
            by_kind[kind] = st
    ctx.db.flush()
    return funnel, by_kind


def _sync_customers(ctx) -> dict[str, Contact]:
    cursor, seen = None, 0
    while seen < MAX_CUSTOMERS:
        data = _get(ctx, "/v2/customers", limit=100, **({"cursor": cursor} if cursor else {}))
        for c in data.get("customers", []):
            seen += 1
            contact = find_external(ctx.db, Contact, "square", c["id"])
            first = c.get("given_name") or c.get("company_name") or c.get("nickname") or \
                (c.get("email_address") or "").split("@")[0] or "Square customer"
            if contact is None:
                contact = Contact(external_source="square", external_id=c["id"], first_name=first[:80],
                                  status="customer", source_channel_id=ctx.channel.id, tags="square")
                ctx.db.add(contact)
                ctx.count("contacts_created")
            else:
                ctx.count("contacts_updated")
            contact.last_name = (c.get("family_name") or contact.last_name or "")[:80]
            contact.email = c.get("email_address") or contact.email
            contact.phone = c.get("phone_number") or contact.phone
            contact.company = (c.get("company_name") or contact.company or "")[:120]
            if c.get("note") and not contact.notes:
                contact.notes = c["note"]
        cursor = data.get("cursor")
        if not cursor:
            break
    ctx.db.flush()
    ctx.metric("square_customers", seen, "Customers in Square directory", "num", "Sales", combine="sum")
    return {c.external_id: c for c in ctx.db.scalars(select(Contact).where(Contact.external_source == "square"))}


def _catalog_metrics(ctx) -> None:
    """How many items / variations you sell and how many are in stock (best effort)."""
    items = variations = 0
    cursor, pages = None, 0
    try:
        while pages < 20:
            data = _get(ctx, "/v2/catalog/list", types="ITEM", **({"cursor": cursor} if cursor else {}))
            for o in data.get("objects") or []:
                if o.get("is_deleted"):
                    continue
                items += 1
                variations += len((o.get("item_data") or {}).get("variations") or [])
            cursor, pages = data.get("cursor"), pages + 1
            if not cursor:
                break
    except SyncError as e:
        ctx.warnings.append(f"Catalog counts unavailable ({e}).")
        return
    ctx.metric("square_items", items, "Catalog items", "num", "Products")
    ctx.metric("square_variations", variations, "Item variations (sizes, colors...)", "num", "Products")


def _money(m) -> float:
    return (m or {}).get("amount", 0) / 100.0


def _payments(ctx, since, loc_ids) -> dict[str, list[dict]]:
    """Payments (card brand/last4, fees, receipt) grouped by order id."""
    by_order: dict[str, list[dict]] = {}
    for loc in loc_ids:
        cursor, n = None, 0
        while n < MAX_ORDERS * 2:
            params = {"begin_time": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "location_id": loc, "limit": 100,
                      "sort_order": "DESC"}
            if cursor:
                params["cursor"] = cursor
            try:
                data = _get(ctx, "/v2/payments", **params)
            except SyncError as e:
                ctx.warnings.append(f"Payment details unavailable ({e}).")
                return by_order
            for p in data.get("payments", []):
                n += 1
                if p.get("order_id"):
                    by_order.setdefault(p["order_id"], []).append(p)
            cursor = data.get("cursor")
            if not cursor:
                break
    return by_order


def _contact_for(ctx, o, contacts, name, email, phone) -> Contact | None:
    if o.get("customer_id") and o["customer_id"] in contacts:
        return contacts[o["customer_id"]]
    if not email:
        return None
    c = ctx.db.scalar(select(Contact).where(Contact.email == email.lower()))
    if c is None:
        first, _, last = (name or email.split("@")[0]).partition(" ")
        c = Contact(first_name=first[:80] or "Customer", last_name=last[:80], email=email.lower(), phone=phone or "",
                    status="customer", source_channel_id=ctx.channel.id, tags="square")
        ctx.db.add(c)
        ctx.db.flush()
        ctx.count("contacts_created")
    elif c.status in ("lead", "prospect"):
        c.status = "customer"
    return c


def _recipient(o) -> dict:
    for f in o.get("fulfillments") or []:
        for k in ("shipment_details", "pickup_details", "delivery_details", "digital_details"):
            r = (f.get(k) or {}).get("recipient")
            if r:
                return r
    return {}


def _payment_summary(o, pays) -> str:
    parts = []
    for p in pays or []:
        card = (p.get("card_details") or {}).get("card") or {}
        if card:
            parts.append(f"{card.get('card_brand', 'Card').replace('_', ' ').title()} ••{card.get('last_4', '')}")
        else:
            parts.append((p.get("source_type") or "Payment").replace("_", " ").title())
    if not parts:
        for t in o.get("tenders") or []:
            card = (t.get("card_details") or {}).get("card") or {}
            parts.append(f"{card.get('card_brand', '').replace('_', ' ').title()} ••{card.get('last_4', '')}".strip()
                         if card else (t.get("type") or "").replace("_", " ").title())
    return ", ".join(dict.fromkeys(p for p in parts if p))[:200]


def _save_order(ctx, o, pays, locations, contacts, funnel, stages) -> float:
    order = ctx.db.scalar(select(Order).where(Order.source == "square", Order.external_id == o["id"]))
    if not pays and order is not None:
        pays = json.loads(order.payments or "[]")   # payment is older than this sync window: keep what we had
    gross = _money(o.get("total_money"))
    refunded = _money((o.get("return_amounts") or {}).get("total_money"))
    refunded = max(refunded, sum(_money(r.get("amount_money")) for r in o.get("refunds") or []
                                 if r.get("status") in (None, "APPROVED", "COMPLETED")))
    net = round(max(gross - refunded, 0.0), 2)
    items = o.get("line_items") or []
    names = [f"{li.get('name') or 'Item'}{' (' + li['variation_name'] + ')' if li.get('variation_name') and li.get('variation_name') != 'Regular' else ''}"
             + (f" ×{li.get('quantity')}" if li.get("quantity") not in (None, "1") else "") for li in items]
    summary = ", ".join(names)
    qty = 0.0
    for li in items:
        try:
            qty += float(li.get("quantity") or 0)
        except ValueError:
            pass
    rec = _recipient(o)
    name = rec.get("display_name") or ""
    email = (rec.get("email_address") or next((p.get("buyer_email_address") for p in pays if p.get("buyer_email_address")), "") or "")
    phone = rec.get("phone_number") or ""
    contact = _contact_for(ctx, o, contacts, name, email, phone)
    if contact and not name:
        name = f"{contact.first_name} {contact.last_name}".strip()
        email = email or contact.email
    ful = (o.get("fulfillments") or [{}])[0]
    state = o.get("state", "")
    fee = sum(_money(f.get("amount_money")) for p in pays for f in p.get("processing_fee") or [])
    fee = fee or sum(_money(t.get("processing_fee_money")) for t in o.get("tenders") or [])

    # Deal in the Square Sales funnel
    fully_refunded = gross > 0 and refunded >= gross
    kind = "lost" if state == "CANCELED" or fully_refunded else ("won" if state == "COMPLETED" else "open")
    stage = stages[kind]
    deal = find_external(ctx.db, Deal, "square", o["id"])
    if deal is None:
        deal = Deal(external_source="square", external_id=o["id"], funnel_id=funnel.id, stage_id=stage.id,
                    status=stage.kind, channel_id=ctx.channel.id)
        ctx.db.add(deal)
        ctx.count("deals_created")
    else:
        ctx.count("deals_updated")
        if deal.status != stage.kind or deal.funnel_id != funnel.id:
            deal.funnel_id, deal.stage_id, deal.status = funnel.id, stage.id, stage.kind
    short = (summary[:120] + ("…" if len(summary) > 120 else "")) or "Square sale"
    deal.title = f"Square: {short}"[:160]
    deal.value = net
    deal.closed_at = parse_dt(o.get("closed_at")) if kind != "open" else None
    if parse_dt(o.get("created_at")):
        deal.created_at = parse_dt(o.get("created_at"))   # date the deal by the order, not the sync
    if contact:
        deal.contact_id = contact.id
    ctx.db.flush()

    if order is None:
        order = Order(source="square", external_id=o["id"], channel_id=ctx.channel.id)
        ctx.db.add(order)
        ctx.count("orders_created")
    else:
        ctx.count("orders_updated")
    order.deal_id, order.contact_id = deal.id, contact.id if contact else order.contact_id
    order.location_id = o.get("location_id", "")
    order.location_name = locations.get(order.location_id, "")
    order.reference = (o.get("ticket_name") or o.get("reference_id") or o["id"][-6:].upper())[:120]
    order.state = state
    order.source_name = ((o.get("source") or {}).get("name") or "")[:120]
    order.customer_name, order.customer_email, order.customer_phone = name[:200], (email or "")[:255], phone[:60]
    order.currency = (o.get("total_money") or {}).get("currency", "USD")
    order.subtotal = round(sum(_money(li.get("gross_sales_money")) for li in items), 2)
    order.discount_total = _money(o.get("total_discount_money"))
    order.tax_total = _money(o.get("total_tax_money"))
    order.tip_total = _money(o.get("total_tip_money"))
    order.service_charge_total = _money(o.get("total_service_charge_money"))
    order.total, order.refunded, order.net = gross, round(refunded, 2), net
    order.processing_fee = round(fee, 2)
    order.item_count, order.items_summary = qty, summary
    order.fulfillment_type = (ful.get("type") or "")[:40]
    order.fulfillment_state = (ful.get("state") or "")[:40]
    order.payment_summary = _payment_summary(o, pays)
    order.receipt_url = next((p.get("receipt_url") for p in pays if p.get("receipt_url")), "") or ""
    order.ordered_at = parse_dt(o.get("created_at"))
    order.updated_at_ext = parse_dt(o.get("updated_at"))
    order.closed_at = parse_dt(o.get("closed_at"))
    order.raw = json.dumps(o)
    order.payments = json.dumps(pays)
    return 0.0 if kind == "lost" else net


def sync(ctx: SyncContext) -> None:
    locs = _locations(ctx)
    if not locs:
        raise SyncError("Square: no active locations found on this account")
    locations = {loc["id"]: loc.get("name", "") for loc in locs}
    ctx.metric("square_locations", len(locs), "Active locations", "num", "Sales")
    _catalog_metrics(ctx)
    contacts = _sync_customers(ctx)
    funnel, stages = _funnel(ctx)

    days = max(1, min(int(ctx.config.get("history_days") or 365), 3650))
    # Re-pull everything once after upgrading to the Orders tab, then only changes since the last sync.
    has_orders = ctx.db.scalar(select(Order.id).where(Order.source == "square").limit(1)) is not None
    since = (ctx.last_sync_at - timedelta(days=2)) if (ctx.last_sync_at and has_orders) else (utcnow() - timedelta(days=days))
    loc_ids = list(locations)[:10]
    pays = _payments(ctx, since - timedelta(days=1), loc_ids)
    body = {"location_ids": loc_ids, "limit": 500, "return_entries": False, "query": {
        "filter": {"state_filter": {"states": ["OPEN", "COMPLETED", "CANCELED"]},
                   "date_time_filter": {"updated_at": {"start_at": since.strftime("%Y-%m-%dT%H:%M:%SZ")}}},
        "sort": {"sort_field": "UPDATED_AT", "sort_order": "DESC"}}}
    total, revenue = 0, 0.0
    while total < MAX_ORDERS:
        data = _post(ctx, "/v2/orders/search", body)
        for o in data.get("orders", []):
            total += 1
            revenue += _save_order(ctx, o, pays.get(o["id"], []), locations, contacts, funnel, stages)
        body["cursor"] = data.get("cursor")
        if not body["cursor"]:
            break
    ctx.stats["orders_synced"] = total
    ctx.stats["revenue_synced"] = round(revenue, 2)

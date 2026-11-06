"""Square: customers -> Contacts, completed orders -> won Deals in a "Square Sales" funnel."""
from datetime import timedelta

from sqlalchemy import select

from ..models import Contact, Deal, Funnel, FunnelStage, utcnow
from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, find_external, parse_dt

SQUARE_VERSION = "2026-09-16"
FUNNEL_NAME = "Square Sales"
MAX_CUSTOMERS = 5000
MAX_ORDERS = 5000

INFO = ProviderInfo(
    key="square", name="Square", platform="square", channel_kind="direct",
    summary="Your Square customers become contacts and completed orders become won deals.",
    syncs=["Customers → Contacts", "Completed orders → won deals (Square Sales funnel)", "Refunds subtracted from deal value"],
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


def _funnel(ctx) -> tuple[Funnel, dict[str, FunnelStage]]:
    funnel = ctx.db.scalar(select(Funnel).where(Funnel.name == FUNNEL_NAME))
    if funnel is None:
        funnel = Funnel(name=FUNNEL_NAME, description="Created automatically from Square orders.")
        funnel.stages = [FunnelStage(name="Open order", position=0, probability=50, kind="open"),
                         FunnelStage(name="Paid", position=1, probability=100, kind="won"),
                         FunnelStage(name="Refunded / canceled", position=2, probability=0, kind="lost")]
        ctx.db.add(funnel)
        ctx.db.flush()
    by_kind: dict[str, FunnelStage] = {}
    for st in sorted(funnel.stages, key=lambda s: s.position):
        by_kind.setdefault(st.kind, st)
    for kind, name in (("open", "Open order"), ("won", "Paid"), ("lost", "Refunded / canceled")):
        if kind not in by_kind:   # user deleted a stage: recreate it
            st = FunnelStage(funnel_id=funnel.id, name=name, position=len(funnel.stages), kind=kind,
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
    return {c.external_id: c for c in ctx.db.scalars(select(Contact).where(Contact.external_source == "square"))}


def _money(m) -> float:
    return (m or {}).get("amount", 0) / 100.0


def sync(ctx: SyncContext) -> None:
    locations = _locations(ctx)
    if not locations:
        raise SyncError("Square: no active locations found on this account")
    contacts = _sync_customers(ctx)
    funnel, stages = _funnel(ctx)

    days = max(1, min(int(ctx.config.get("history_days") or 365), 3650))
    since = (ctx.last_sync_at - timedelta(days=2)) if ctx.last_sync_at else (utcnow() - timedelta(days=days))
    loc_ids = [loc["id"] for loc in locations][:10]
    body = {"location_ids": loc_ids, "limit": 500, "return_entries": False, "query": {
        "filter": {"state_filter": {"states": ["COMPLETED"]},
                   "date_time_filter": {"closed_at": {"start_at": since.strftime("%Y-%m-%dT%H:%M:%SZ")}}},
        "sort": {"sort_field": "CLOSED_AT", "sort_order": "DESC"}}}
    total, revenue = 0, 0.0
    while total < MAX_ORDERS:
        data = _post(ctx, "/v2/orders/search", body)
        for o in data.get("orders", []):
            total += 1
            gross = _money(o.get("total_money"))
            refunded = _money((o.get("return_amounts") or {}).get("total_money"))
            value = round(max(gross - refunded, 0.0), 2)
            items = [li.get("name") or "Item" for li in o.get("line_items", [])]
            title = (", ".join(items[:3]) + (f" +{len(items) - 3} more" if len(items) > 3 else "")) or "Square sale"
            fully_refunded = gross > 0 and refunded >= gross
            stage = stages["lost"] if fully_refunded else stages["won"]
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
            deal.title = f"Square: {title}"[:160]
            deal.value = value
            deal.closed_at = parse_dt(o.get("closed_at")) or deal.closed_at
            if o.get("customer_id") and o["customer_id"] in contacts:
                deal.contact_id = contacts[o["customer_id"]].id
            if not fully_refunded:
                revenue += value
        body["cursor"] = data.get("cursor")
        if not body["cursor"]:
            break
    ctx.stats["orders_synced"] = total
    ctx.stats["revenue_synced"] = round(revenue, 2)

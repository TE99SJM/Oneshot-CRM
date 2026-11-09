"""Channel data: every number the APIs give us + numbers the CRM works out itself, which ones you
chose to show on each channel, and the dashboard's combined totals per channel type.

Two kinds of metric:
  api  - saved at each sync (ChannelMetric) with a daily history (MetricSnapshot). "now" values
         (followers, lifetime views...) show the change over the chosen period from that history.
         "28d"/"30d" values are the platform's own rolling window.
  crm  - worked out live from synced posts, orders, contacts, deals and emails for the chosen period.
"""
import json
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Channel, ChannelMetric, Contact, Deal, Email, MetricSnapshot, Order, Post, utcnow

GROUPS = {"social": "social", "marketplace": "sales", "website": "sales", "direct": "sales",
          "email": "email", "ads": "ads", "other": "other"}
GROUP_LABELS = {"social": "Social media", "sales": "Sales channels", "email": "Email", "ads": "Paid ads", "other": "Other"}
GROUP_ORDER = ["social", "sales", "email", "ads", "other"]

# key: (label, unit, section, combine). Providers may send other keys with their own label.
CATALOG: dict[str, tuple[str, str, str, str]] = {
    # audience
    "followers": ("Followers / subscribers", "num", "Audience", "sum"),
    "subscribers": ("Subscribers", "num", "Audience", "sum"),
    "following": ("Following", "num", "Audience", "sum"),
    "page_likes": ("Page likes", "num", "Audience", "sum"),
    "talking_about": ("People talking about this", "num", "Audience", "sum"),
    "total_likes_received": ("Total likes received", "num", "Engagement", "sum"),
    # views / reach
    "total_views": ("Lifetime views", "num", "Views", "sum"),
    "video_count": ("Videos / posts (platform count)", "num", "Content", "sum"),
    "media_count": ("Posts on profile", "num", "Content", "sum"),
    # live
    "live_now": ("Live right now", "num", "Live", "sum"),
    "live_viewers": ("Live viewers right now", "num", "Live", "sum"),
    # crm-derived content
    "posts": ("Posts published", "num", "Content", "sum"),
    "posts_all": ("Posts synced (all time)", "num", "Content", "sum"),
    "post_views": ("Views on posts published", "num", "Views", "sum"),
    "post_views_all": ("Views on all synced posts", "num", "Views", "sum"),
    "likes": ("Likes / reactions", "num", "Engagement", "sum"),
    "comments": ("Comments", "num", "Engagement", "sum"),
    "shares": ("Shares", "num", "Engagement", "sum"),
    "clicks": ("Link clicks", "num", "Engagement", "sum"),
    "engagement": ("Total engagements", "num", "Engagement", "sum"),
    "engagement_rate": ("Engagement rate", "pct", "Engagement", "avg"),
    "avg_views_per_post": ("Average views per post", "num", "Views", "avg"),
    "top_post_views": ("Best post's views", "num", "Views", "none"),
    # crm-derived sales
    "orders": ("Orders", "num", "Sales", "sum"),
    "orders_all": ("Orders (all time)", "num", "Sales", "sum"),
    "gross_sales": ("Gross sales", "money", "Sales", "sum"),
    "gross_sales_all": ("Gross sales (all time)", "money", "Sales", "sum"),
    "net_sales": ("Net sales (after refunds)", "money", "Sales", "sum"),
    "refunds": ("Refunds", "money", "Sales", "sum"),
    "fees": ("Processing / platform fees", "money", "Sales", "sum"),
    "tax": ("Tax collected", "money", "Sales", "sum"),
    "tips": ("Tips", "money", "Sales", "sum"),
    "discounts": ("Discounts given", "money", "Sales", "sum"),
    "avg_order_value": ("Average order value", "money", "Sales", "avg"),
    "items_sold": ("Items sold", "num", "Sales", "sum"),
    "buyers": ("Unique buyers", "num", "Sales", "sum"),
    "repeat_buyers": ("Repeat buyers", "num", "Sales", "sum"),
    "canceled_orders": ("Canceled orders", "num", "Sales", "sum"),
    "open_orders": ("Open / unshipped orders", "num", "Sales", "sum"),
    # crm
    "leads": ("New leads (contacts)", "num", "CRM", "sum"),
    "contacts_all": ("Contacts from this channel (all time)", "num", "CRM", "sum"),
    "won_revenue": ("Won deal revenue", "money", "CRM", "sum"),
    "open_pipeline": ("Open pipeline value", "money", "CRM", "sum"),
    "monthly_cost": ("Monthly cost", "money", "CRM", "sum"),
    # email
    "emails": ("Emails", "num", "Email", "sum"),
    "emails_in": ("Emails received", "num", "Email", "sum"),
    "emails_out": ("Emails sent", "num", "Email", "sum"),
    "emails_unread": ("Unread emails", "num", "Email", "sum"),
    "email_people": ("People emailed with", "num", "Email", "sum"),
}
WINDOW_LABELS = {"now": "right now", "28d": "last 28 days", "30d": "last 30 days", "60d": "last 60 days",
                 "90d": "last 90 days", "live": "live", "all": "all time", "period": "selected period"}

DEFAULTS = {
    "social": ["followers", "total_views", "post_views", "posts", "likes", "comments", "engagement_rate"],
    "sales": ["orders", "gross_sales", "net_sales", "avg_order_value", "items_sold", "buyers", "refunds",
              "visitors", "page_views"],
    "email": ["emails_in", "emails_out", "email_people", "emails_unread"],
}
DEFAULTS_ANY = ["followers", "leads", "won_revenue", "open_pipeline"]


def group_of(ch: Channel) -> str:
    return GROUPS.get(ch.kind or "other", "other")


# ---------------------------------------------------------------- saving API metrics after a sync
def save_api_metrics(db: Session, channel_id: int, provider: str, metrics: dict) -> int:
    today = utcnow().date()
    existing = {m.key: m for m in db.scalars(select(ChannelMetric).where(ChannelMetric.channel_id == channel_id)).all()}
    snaps = {s.key: s for s in db.scalars(select(MetricSnapshot).where(MetricSnapshot.channel_id == channel_id,
                                                                       MetricSnapshot.day == today)).all()}
    for key, m in metrics.items():
        label, unit, section, combine = CATALOG.get(key, (None, None, None, None))
        row = existing.get(key)
        if row is None:
            row = ChannelMetric(channel_id=channel_id, key=key)
            db.add(row)
        row.label = (m.get("label") or label or key.replace("_", " ").capitalize())[:160]
        row.unit = m.get("unit") or unit or "num"
        row.section = m.get("section") or section or "General"
        row.window = m.get("window") or "now"
        row.combine = m.get("combine") or combine or ("avg" if row.unit in ("pct", "seconds", "stars") else "sum")
        row.value = float(m["value"])
        row.provider = provider
        row.updated_at = utcnow()
        snap = snaps.get(key)
        if snap is None:
            db.add(MetricSnapshot(channel_id=channel_id, key=key, day=today, value=row.value))
        else:
            snap.value = row.value
    return len(metrics)


def _change(history: list[MetricSnapshot], value: float, start_day: date | None) -> float | None:
    """Value now minus the last reading before the period began (None = no history that far back)."""
    if start_day is None or not history:
        return None
    prior = [s for s in history if s.day < start_day]
    return round(value - prior[-1].value, 2) if prior else None


# ---------------------------------------------------------------- CRM-derived numbers
def _in(dt: datetime | None, lo: datetime | None, hi: datetime | None) -> bool:
    return dt is not None and (lo is None or dt >= lo) and (hi is None or dt < hi)


def derived(db: Session, ch: Channel, lo: datetime | None, hi: datetime | None, cache: dict | None = None) -> dict:
    """{key: value} worked out from the CRM's own synced records for this channel and period."""
    c = cache if cache is not None else {}
    if "posts" not in c:
        c["posts"], c["orders"], c["contacts"], c["deals"], c["emails"] = (defaultdict(list) for _ in range(5))
        for p in db.scalars(select(Post).where(Post.status == "published")).all():
            c["posts"][p.channel_id].append(p)
        for o in db.scalars(select(Order)).all():
            c["orders"][o.channel_id].append(o)
        for x in db.scalars(select(Contact)).all():
            c["contacts"][x.source_channel_id].append(x)
        for d in db.scalars(select(Deal)).all():
            c["deals"][d.channel_id].append(d)
        for e in db.scalars(select(Email)).all():
            c["emails"][e.channel_id].append(e)
    out: dict[str, float] = {}
    posts = c["posts"].get(ch.id, [])
    if posts:
        pp = [p for p in posts if _in(p.published_at, lo, hi)] if (lo or hi) else posts
        views = sum(p.views for p in pp)
        eng = sum(p.likes + p.comments + p.shares + p.clicks for p in pp)
        out.update(posts=len(pp), posts_all=len(posts), post_views=views, post_views_all=sum(p.views for p in posts),
                   likes=sum(p.likes for p in pp), comments=sum(p.comments for p in pp),
                   shares=sum(p.shares for p in pp), clicks=sum(p.clicks for p in pp), engagement=eng)
        if views:
            out["engagement_rate"] = round(eng / views * 100, 2)
        if pp:
            out["avg_views_per_post"] = round(views / len(pp), 1)
            out["top_post_views"] = max(p.views for p in pp)
    orders = c["orders"].get(ch.id, [])
    if orders:
        op = [o for o in orders if _in(o.ordered_at, lo, hi)] if (lo or hi) else orders
        canceled = [o for o in op if (o.state or "").upper() in ("CANCELED", "CANCELLED")]
        good = [o for o in op if o not in canceled and (o.state or "").upper() != "DRAFT"]
        gross = sum(o.total for o in good)
        who = [(o.customer_email or o.buyer_username or o.customer_name or "").lower() for o in good]
        who = [w for w in who if w]
        counts = defaultdict(int)
        for w in who:
            counts[w] += 1
        out.update(orders=len(good), orders_all=sum(1 for o in orders if (o.state or "").upper() not in
                                                    ("CANCELED", "CANCELLED", "DRAFT")),
                   gross_sales=round(gross, 2), gross_sales_all=round(sum(o.total for o in orders if (o.state or "").upper()
                                                                          not in ("CANCELED", "CANCELLED", "DRAFT")), 2),
                   net_sales=round(sum(o.net for o in good), 2), refunds=round(sum(o.refunded for o in op), 2),
                   fees=round(sum(o.processing_fee for o in good), 2), tax=round(sum(o.tax_total for o in good), 2),
                   tips=round(sum(o.tip_total for o in good), 2), discounts=round(sum(o.discount_total for o in good), 2),
                   items_sold=round(sum(o.item_count for o in good), 2), buyers=len(counts),
                   repeat_buyers=sum(1 for n in counts.values() if n > 1), canceled_orders=len(canceled),
                   open_orders=sum(1 for o in good if (o.state or "").upper() == "OPEN" or
                                   (o.fulfillment_state or "").upper() in ("NOT_STARTED", "PROPOSED", "RESERVED",
                                                                           "PREPARED", "AWAITING_SHIPMENT", "UNPAID")))
        if good:
            out["avg_order_value"] = round(gross / len(good), 2)
    contacts = c["contacts"].get(ch.id, [])
    if contacts:
        out["leads"] = sum(1 for x in contacts if _in(x.created_at, lo, hi)) if (lo or hi) else len(contacts)
        out["contacts_all"] = len(contacts)
    deals = c["deals"].get(ch.id, [])
    if deals:
        out["won_revenue"] = round(sum(d.value for d in deals if d.status == "won" and
                                       ((not lo and not hi) or _in(d.closed_at or d.updated_at, lo, hi))), 2)
        out["open_pipeline"] = round(sum(d.value for d in deals if d.status == "open"), 2)
    emails = c["emails"].get(ch.id, [])
    if emails:
        ep = [e for e in emails if _in(e.sent_at, lo, hi)] if (lo or hi) else emails
        people = {(e.from_email if e.direction == "in" else (e.to_addrs or "").split(",")[0]).lower() for e in ep if not e.bulk}
        out.update(emails=len(ep), emails_in=sum(1 for e in ep if e.direction == "in"),
                   emails_out=sum(1 for e in ep if e.direction == "out"), emails_unread=sum(1 for e in emails if e.unread),
                   email_people=len({p for p in people if p}))
    if ch.monthly_cost:
        out["monthly_cost"] = ch.monthly_cost
    if ch.followers and "followers" not in out:
        out["followers"] = ch.followers           # manual channels: the number typed on the channel
    return out


# ---------------------------------------------------------------- one channel's full list
def _entry(key: str, value: float, source: str, window: str, row: ChannelMetric | None = None, change=None) -> dict:
    label, unit, section, combine = CATALOG.get(key, (None, None, None, None))
    return {"key": key, "label": (row.label if row else None) or label or key.replace("_", " ").capitalize(),
            "value": value, "unit": (row.unit if row else None) or unit or "num",
            "section": (row.section if row else None) or section or "General",
            "window": window, "window_label": WINDOW_LABELS.get(window, window), "source": source,
            "combine": (row.combine if row else None) or combine or "sum", "change": change,
            "updated_at": row.updated_at.isoformat() if row else None, "provider": row.provider if row else ""}


def display_keys(ch: Channel) -> tuple[list[str], bool]:
    try:
        keys = json.loads(ch.display_metrics) if ch.display_metrics else None
    except ValueError:
        keys = None
    if isinstance(keys, list):
        return [str(k) for k in keys], False
    return list(dict.fromkeys(DEFAULTS.get(group_of(ch), []) + DEFAULTS_ANY)), True


def channel_metrics(db: Session, ch: Channel, lo: datetime | None, hi: datetime | None, cache: dict | None = None) -> dict:
    rows = db.scalars(select(ChannelMetric).where(ChannelMetric.channel_id == ch.id)).all()
    hist: dict[str, list] = defaultdict(list)
    for s in db.scalars(select(MetricSnapshot).where(MetricSnapshot.channel_id == ch.id)
                        .order_by(MetricSnapshot.day)).all():
        hist[s.key].append(s)
    start_day = lo.date() if lo else None
    items: dict[str, dict] = {}
    for r in rows:
        ch_ = _change(hist.get(r.key, []), r.value, start_day) if r.window == "now" else None
        items[r.key] = _entry(r.key, r.value, "api", r.window, r, ch_)
    for key, value in derived(db, ch, lo, hi, cache).items():
        if key in items:
            continue                                   # the platform's own number wins (e.g. followers)
        window = "all" if key.endswith("_all") or key in ("contacts_all", "open_pipeline", "monthly_cost",
                                                          "emails_unread") else ("period" if (lo or hi) else "all")
        if key == "followers":
            window = "now"
        items[key] = _entry(key, value, "crm", window)
    shown, is_default = display_keys(ch)
    order = {s: i for i, s in enumerate(["Audience", "Views", "Content", "Engagement", "Watch time", "Live", "Sales",
                                         "Listings", "Products", "Traffic", "Revenue", "Email", "CRM", "General"])}
    ordered = sorted(items.values(), key=lambda m: (order.get(m["section"], 99), m["label"]))
    return {"channel": {"id": ch.id, "name": ch.name, "kind": ch.kind, "platform": ch.platform, "active": ch.active,
                        "group": group_of(ch), "group_label": GROUP_LABELS[group_of(ch)]},
            "metrics": ordered, "display": [k for k in shown if k in items] if is_default else shown,
            "is_default": is_default}


def all_channels(db: Session, lo: datetime | None, hi: datetime | None) -> list[dict]:
    cache: dict = {}
    return [channel_metrics(db, ch, lo, hi, cache) for ch in db.scalars(select(Channel).order_by(Channel.name)).all()]


# ---------------------------------------------------------------- dashboard: combined per type
def combined(db: Session, lo: datetime | None, hi: datetime | None) -> dict:
    """For each channel type, add up the metrics you chose to show, across the channels that show them."""
    groups: dict[str, dict] = {}
    for data in all_channels(db, lo, hi):
        ch = data["channel"]
        if not ch["active"]:
            continue
        g = groups.setdefault(ch["group"], {"key": ch["group"], "label": GROUP_LABELS[ch["group"]], "channels": [],
                                            "metrics": {}})
        g["channels"].append({"id": ch["id"], "name": ch["name"], "platform": ch["platform"]})
        by_key = {m["key"]: m for m in data["metrics"]}
        for key in dict.fromkeys(data["display"]):
            m = by_key.get(key)
            if not m:
                continue
            agg = g["metrics"].setdefault(key, {"key": key, "label": m["label"], "unit": m["unit"],
                                                "section": m["section"], "combine": m["combine"],
                                                "windows": set(), "per_channel": []})
            agg["windows"].add(m["window_label"])
            agg["per_channel"].append({"channel_id": ch["id"], "channel": ch["name"], "platform": ch["platform"],
                                       "value": m["value"], "change": m["change"], "window_label": m["window_label"]})
    out = []
    for key in GROUP_ORDER:
        g = groups.get(key)
        if not g:
            continue
        metrics = []
        for agg in g["metrics"].values():
            vals = [p["value"] for p in agg["per_channel"]]
            if agg["combine"] == "avg":
                total = round(sum(vals) / len(vals), 2) if vals else 0
            elif agg["combine"] == "none":
                total = max(vals) if vals else 0
            else:
                total = round(sum(vals), 2)
            changes = [p["change"] for p in agg["per_channel"] if p["change"] is not None]
            agg["per_channel"].sort(key=lambda p: p["value"], reverse=True)
            metrics.append({**agg, "total": total, "windows": sorted(agg["windows"]),
                            "change": round(sum(changes), 2) if changes and agg["combine"] == "sum" else None,
                            "channels": len(vals)})
        order = {s: i for i, s in enumerate(["Audience", "Views", "Sales", "Engagement", "Content", "Watch time",
                                             "Traffic", "Revenue", "Live", "Listings", "Products", "Email", "CRM"])}
        metrics.sort(key=lambda m: (order.get(m["section"], 99), -m["channels"], m["label"]))
        out.append({"key": g["key"], "label": g["label"], "channels": g["channels"], "metrics": metrics})
    return {"groups": out}

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import current_user
from ..models import Activity, Channel, Contact, Deal, Funnel, Post, utcnow
from ..schemas import ActivityOut, PostOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(current_user)])


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    now = utcnow()
    d30 = now - timedelta(days=30)
    channels = db.scalars(select(Channel)).all()
    contacts = db.scalars(select(Contact)).all()
    deals = db.scalars(select(Deal).options(selectinload(Deal.stage))).all()
    posts = db.scalars(select(Post)).all()
    funnels = db.scalars(select(Funnel).options(selectinload(Funnel.stages)).order_by(Funnel.id)).all()

    open_deals = [d for d in deals if d.status == "open"]
    won = [d for d in deals if d.status == "won"]
    lost = [d for d in deals if d.status == "lost"]
    published_30 = [p for p in posts if p.status == "published" and p.published_at and p.published_at >= d30]
    views_30 = sum(p.views for p in published_30)
    engagement_30 = sum(p.likes + p.comments + p.shares + p.clicks for p in published_30)

    kpis = {
        "contacts": len(contacts),
        "new_contacts_30d": sum(1 for c in contacts if c.created_at >= d30),
        "customers": sum(1 for c in contacts if c.status == "customer"),
        "open_deals": len(open_deals),
        "pipeline_value": round(sum(d.value for d in open_deals), 2),
        "weighted_pipeline": round(sum(d.value * d.stage.probability / 100 for d in open_deals), 2),
        "won_revenue_30d": round(sum(d.value for d in won if d.closed_at and d.closed_at >= d30), 2),
        "won_revenue_total": round(sum(d.value for d in won), 2),
        "win_rate": round(len(won) / (len(won) + len(lost)) * 100, 1) if (won or lost) else None,
        "followers": sum(c.followers for c in channels if c.active),
        "posts_published_30d": len(published_30),
        "views_30d": views_30,
        "engagement_rate_30d": round(engagement_30 / views_30 * 100, 2) if views_30 else None,
        "monthly_channel_cost": round(sum(c.monthly_cost for c in channels if c.active), 2),
    }

    by_channel: dict[int | None, dict] = defaultdict(lambda: {"leads": 0, "won": 0.0, "pipeline": 0.0, "views": 0})
    for c in contacts:
        by_channel[c.source_channel_id]["leads"] += 1
    for d in deals:
        if d.status == "won":
            by_channel[d.channel_id]["won"] += d.value
        elif d.status == "open":
            by_channel[d.channel_id]["pipeline"] += d.value
    for p in posts:
        by_channel[p.channel_id]["views"] += p.views
    names = {c.id: c.name for c in channels}
    channel_rows = [
        {"channel_id": cid, "channel": names.get(cid, "Unattributed"), **{k: round(v, 2) for k, v in vals.items()}}
        for cid, vals in by_channel.items()
    ]
    channel_rows.sort(key=lambda r: (r["won"], r["pipeline"], r["leads"]), reverse=True)

    funnel_rows = []
    for f in funnels:
        fdeals = [d for d in deals if d.funnel_id == f.id]
        stages = []
        for s in f.stages:
            sd = [d for d in fdeals if d.stage_id == s.id]
            stages.append({"id": s.id, "name": s.name, "kind": s.kind, "count": len(sd),
                           "value": round(sum(d.value for d in sd), 2)})
        fwon = sum(1 for d in fdeals if d.status == "won")
        funnel_rows.append({"id": f.id, "name": f.name, "total": len(fdeals), "stages": stages,
                            "conversion": round(fwon / len(fdeals) * 100, 1) if fdeals else None})

    months = []
    for i in range(5, -1, -1):
        y, m = now.year, now.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        total = sum(d.value for d in won if d.closed_at and d.closed_at.year == y and d.closed_at.month == m)
        months.append({"month": f"{y}-{m:02d}", "won": round(total, 2)})

    upcoming = sorted(
        (p for p in posts if p.status in ("draft", "scheduled") and p.scheduled_at
         and now <= p.scheduled_at <= now + timedelta(days=14)),
        key=lambda p: p.scheduled_at,
    )[:8]
    tasks = db.scalars(select(Activity).where(Activity.kind == "task", Activity.done.is_(False))
                       .order_by(Activity.due_at.is_(None), Activity.due_at).limit(8)).all()

    return {
        "kpis": kpis,
        "channels": channel_rows,
        "funnels": funnel_rows,
        "revenue_by_month": months,
        "upcoming_posts": [PostOut.model_validate(p).model_dump(mode="json") for p in upcoming],
        "open_tasks": [
            {**ActivityOut.model_validate(t).model_dump(mode="json"), "overdue": bool(t.due_at and t.due_at < now)}
            for t in tasks
        ],
    }

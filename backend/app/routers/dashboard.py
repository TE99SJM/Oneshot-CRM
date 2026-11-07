from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import current_user
from ..models import Activity, Channel, Contact, Deal, Funnel, Post, utcnow
from ..schemas import ActivityOut, PostOut
from ..stats_history import METRICS, record_snapshots, series, views_gained

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(current_user)])


def _period(start: date | None, end: date | None, tz_offset: int):
    """Local [start, end] dates -> UTC datetime bounds [lo, hi). None start = all time."""
    off = timedelta(minutes=tz_offset)
    lo = datetime.combine(start, datetime.min.time()) - off if start else None
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time()) - off if end else None
    return lo, hi


@router.get("")
def dashboard(start: date | None = None, end: date | None = None,
              tz_offset: int = Query(0, ge=-840, le=840, description="minutes to add to UTC for local time"),
              db: Session = Depends(get_db)):
    """Totals for the chosen period (start/end are local dates; omit both for all time).
    Open pipeline and audience are always 'right now'."""
    if start and end and start > end:
        raise HTTPException(422, "Start date is after end date")
    record_snapshots(db)
    now = utcnow()
    lo, hi = _period(start, end, tz_offset)
    inp = lambda dt: dt is not None and (lo is None or dt >= lo) and (hi is None or dt < hi)  # noqa: E731
    channels = db.scalars(select(Channel)).all()
    contacts = db.scalars(select(Contact)).all()
    deals = db.scalars(select(Deal).options(selectinload(Deal.stage))).all()
    posts = db.scalars(select(Post)).all()
    funnels = db.scalars(select(Funnel).options(selectinload(Funnel.stages)).order_by(Funnel.id)).all()

    closed = lambda d: d.closed_at or d.updated_at  # noqa: E731
    open_deals = [d for d in deals if d.status == "open"]
    won = [d for d in deals if d.status == "won"]
    won_p = [d for d in won if inp(closed(d))]
    lost_p = [d for d in deals if d.status == "lost" and inp(closed(d))]
    published_p = [p for p in posts if p.status == "published" and inp(p.published_at)]
    views_p = sum(p.views for p in published_p)
    engagement_p = sum(p.likes + p.comments + p.shares + p.clicks for p in published_p)
    contacts_p = [c for c in contacts if inp(c.created_at)]
    gained, history_since = views_gained(db, lo.date() if lo else None)

    kpis = {
        "contacts": len(contacts),
        "new_contacts": len(contacts_p),
        "customers": sum(1 for c in contacts if c.status == "customer"),
        "open_deals": len(open_deals),
        "pipeline_value": round(sum(d.value for d in open_deals), 2),
        "weighted_pipeline": round(sum(d.value * d.stage.probability / 100 for d in open_deals), 2),
        "won_revenue": round(sum(d.value for d in won_p), 2),
        "won_deals": len(won_p),
        "won_revenue_total": round(sum(d.value for d in won), 2),
        "win_rate": round(len(won_p) / (len(won_p) + len(lost_p)) * 100, 1) if (won_p or lost_p) else None,
        "closed_deals": len(won_p) + len(lost_p),
        "followers": sum(c.followers for c in channels if c.active),
        "posts_published": len(published_p),
        "views": views_p,                          # views on posts published in the period
        "views_gained": round(gained) if gained is not None else None,   # growth of lifetime views in the period
        "views_history_since": history_since.isoformat() if history_since else None,
        "views_lifetime": sum(c.total_views or 0 for c in channels if c.active),
        "engagement_rate": round(engagement_p / views_p * 100, 2) if views_p else None,
        "monthly_channel_cost": round(sum(c.monthly_cost for c in channels if c.active), 2),
    }

    by_channel: dict[int | None, dict] = defaultdict(lambda: {"leads": 0, "won": 0.0, "pipeline": 0.0, "views": 0,
                                                              "lifetime_views": 0})
    for c in contacts_p:
        by_channel[c.source_channel_id]["leads"] += 1
    for d in won_p:
        by_channel[d.channel_id]["won"] += d.value
    for d in open_deals:
        by_channel[d.channel_id]["pipeline"] += d.value
    for p in published_p:
        by_channel[p.channel_id]["views"] += p.views
    for c in channels:
        if c.active and c.total_views:
            by_channel[c.id]["lifetime_views"] = c.total_views
            g, _ = views_gained(db, lo.date() if lo else None, f"views_total:{c.id}")
            if g is not None:
                by_channel[c.id]["views"] = max(by_channel[c.id]["views"], g)
    names = {c.id: c.name for c in channels}
    channel_rows = [
        {"channel_id": cid, "channel": names.get(cid, "Unattributed"), **{k: round(v, 2) for k, v in vals.items()}}
        for cid, vals in by_channel.items()
    ]
    channel_rows.sort(key=lambda r: (r["won"], r["pipeline"], r["leads"]), reverse=True)

    funnel_rows = []
    for f in funnels:
        fdeals = [d for d in deals if d.funnel_id == f.id and inp(d.created_at)]
        stages = []
        for s in f.stages:
            sd = [d for d in fdeals if d.stage_id == s.id]
            stages.append({"id": s.id, "name": s.name, "kind": s.kind, "count": len(sd),
                           "value": round(sum(d.value for d in sd), 2)})
        fwon = sum(1 for d in fdeals if d.status == "won")
        funnel_rows.append({"id": f.id, "name": f.name, "total": len(fdeals), "stages": stages,
                            "conversion": round(fwon / len(fdeals) * 100, 1) if fdeals else None})

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
        "upcoming_posts": [PostOut.model_validate(p).model_dump(mode="json") for p in upcoming],
        "open_tasks": [
            {**ActivityOut.model_validate(t).model_dump(mode="json"), "overdue": bool(t.due_at and t.due_at < now)}
            for t in tasks
        ],
    }


@router.get("/series/{metric}")
def metric_series(metric: str, start: date | None = None, end: date | None = None,
                  bucket: str = Query("auto", pattern="^(auto|day|week|month)$"),
                  tz_offset: int = Query(0, ge=-840, le=840, description="minutes to add to UTC for local time"),
                  db: Session = Depends(get_db)):
    if metric not in METRICS:
        raise HTTPException(404, f"Unknown metric. Choose one of: {', '.join(METRICS)}")
    if start and end and start > end:
        raise HTTPException(422, "Start date is after end date")
    return series(db, metric, start, end, bucket, tz_offset)

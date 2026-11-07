"""Time series for the dashboard stat cards (clicked to open a full-screen chart)."""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Channel, Contact, Deal, Post, StatSnapshot, utcnow

METRICS = {
    # key: (label, kind, format)   kind: sum = total per period, state = value at end of each period, rate
    "won_revenue": ("Won revenue", "sum", "money"),
    "open_pipeline": ("Open pipeline", "state", "money"),
    "win_rate": ("Win rate", "rate", "pct"),
    "contacts": ("Contacts", "state", "num"),
    "new_contacts": ("New contacts", "sum", "num"),
    "audience": ("Audience", "state", "num"),
    "views": ("Views on new posts", "sum", "num"),
    "views_gained": ("Views gained", "sum", "num"),
    "views_total": ("Lifetime views", "state", "num"),
}


def record_snapshots(db: Session) -> None:
    """Save today's audience total (followers/subscribers across active channels) and lifetime views
    (overall and per channel). One row per metric per day, updated in place. Safe to call often."""
    today = utcnow().date()
    channels = [c for c in db.scalars(select(Channel)).all() if c.active]
    values = {"audience": float(sum(c.followers for c in channels)),
              "views_total": float(sum(c.total_views or 0 for c in channels))}
    for c in channels:
        if c.total_views:
            values[f"views_total:{c.id}"] = float(c.total_views)
    existing = {s.metric: s for s in db.scalars(select(StatSnapshot).where(StatSnapshot.day == today)).all()}
    changed = False
    for metric, value in values.items():
        snap = existing.get(metric)
        if snap is None:
            if metric == "views_total" and not value:
                continue                       # nothing synced yet; don't start history at zero
            db.add(StatSnapshot(metric=metric, day=today, value=value))
            changed = True
        elif snap.value != value:
            snap.value = value
            changed = True
    if changed:
        db.commit()


def views_gained(db: Session, start_day: date | None, metric: str = "views_total") -> tuple[float | None, date | None]:
    """Lifetime views now minus the last reading before start_day (UTC). (None, first_day) when the saved
    history doesn't reach back that far yet."""
    snaps = sorted(db.scalars(select(StatSnapshot).where(StatSnapshot.metric == metric)).all(), key=lambda s: s.day)
    if not snaps:
        return None, None
    first = snaps[0].day
    now = snaps[-1].value
    if start_day is None:
        return now, first                      # all time: everything counted so far
    prior = [s for s in snaps if s.day < start_day]
    if not prior:
        return None, first
    return max(0.0, now - prior[-1].value), first


def _buckets(start: date, end: date, bucket: str) -> list[tuple[date, date]]:
    """[(first_day, last_day)] covering start..end inclusive (local dates)."""
    out = []
    if bucket == "day":
        d = start
        while d <= end:
            out.append((d, d)); d += timedelta(days=1)
    elif bucket == "week":                      # weeks start Monday
        d = start - timedelta(days=start.weekday())
        while d <= end:
            out.append((d, d + timedelta(days=6))); d += timedelta(days=7)
    else:
        d = start.replace(day=1)
        while d <= end:
            nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
            out.append((d, nxt - timedelta(days=1))); d = nxt
    return out


def series(db: Session, metric: str, start: date | None, end: date | None, bucket: str, tz_minutes: int) -> dict:
    label, kind, fmt = METRICS[metric]
    offset = timedelta(minutes=tz_minutes)          # local = utc + offset
    now_utc = utcnow()
    today = (now_utc + offset).date()
    local = lambda dt: (dt + offset).date() if dt else None  # noqa: E731

    deals = db.scalars(select(Deal)).all()
    contacts = db.scalars(select(Contact)).all()
    posts = [p for p in db.scalars(select(Post)).all() if p.status == "published" and p.published_at]
    snap_metric = "views_total" if metric in ("views_total", "views_gained") else "audience"
    snaps = sorted(db.scalars(select(StatSnapshot).where(StatSnapshot.metric == snap_metric)).all(), key=lambda s: s.day)

    def deal_closed(d: Deal) -> datetime | None:
        return d.closed_at or (d.updated_at if d.status in ("won", "lost") else None)

    end = min(end or today, today)
    if start is None:                               # "all time": from the earliest data point for this metric
        dates = {
            "won_revenue": [local(deal_closed(d)) for d in deals if d.status == "won"],
            "win_rate": [local(deal_closed(d)) for d in deals if d.status in ("won", "lost")],
            "open_pipeline": [local(d.created_at) for d in deals],
            "contacts": [local(c.created_at) for c in contacts],
            "new_contacts": [local(c.created_at) for c in contacts],
            "views": [local(p.published_at) for p in posts],
            "audience": [s.day for s in snaps],
            "views_total": [s.day for s in snaps],
            "views_gained": [s.day for s in snaps],
        }[metric]
        dates = [d for d in dates if d]
        start = min(dates) if dates else end - timedelta(days=29)
    start = min(start, end)
    span = (end - start).days + 1
    if bucket == "auto":
        bucket = "day" if span <= 62 else "week" if span <= 366 else "month"
    rows = _buckets(start, end, bucket)

    points = []
    for first, last in rows:
        lo, hi = max(first, start), min(last, end)
        cut = datetime.combine(hi + timedelta(days=1), datetime.min.time()) - offset   # end of period in UTC
        cut = min(cut, now_utc)
        inside = lambda dt: dt is not None and lo <= local(dt) <= hi  # noqa: E731
        value: float | None
        if metric == "won_revenue":
            value = sum(d.value for d in deals if d.status == "won" and inside(deal_closed(d)))
        elif metric == "win_rate":
            won = sum(1 for d in deals if d.status == "won" and inside(deal_closed(d)))
            lost = sum(1 for d in deals if d.status == "lost" and inside(deal_closed(d)))
            value = won / (won + lost) * 100 if won + lost else None
        elif metric == "open_pipeline":
            value = sum(d.value for d in deals if d.created_at < cut
                        and not ((c := deal_closed(d)) and c < cut))
        elif metric == "contacts":
            value = sum(1 for c in contacts if c.created_at < cut)
        elif metric == "new_contacts":
            value = sum(1 for c in contacts if inside(c.created_at))
        elif metric == "views":
            value = sum(p.views for p in posts if inside(p.published_at))
        elif metric == "views_gained":
            end_snap = [x for x in snaps if x.day <= (cut - timedelta(seconds=1)).date()]
            before = [x for x in snaps if x.day < lo]
            value = max(0.0, end_snap[-1].value - before[-1].value) if end_snap and before else None
        else:  # audience / views_total: last reading on or before the end of the period
            prior = [s for s in snaps if s.day <= (cut - timedelta(seconds=1)).date()]
            value = prior[-1].value if prior else None
        points.append({"start": lo.isoformat(), "end": hi.isoformat(),
                       "value": round(value, 2) if value is not None else None})

    vals = [p["value"] for p in points if p["value"] is not None]
    note = ""
    if metric == "audience":
        note = ("Audience history starts the first day this version of the CRM ran — it saves one reading per day "
                "after each sync, so this chart fills in over time.") if len(snaps) < 2 else ""
    elif metric == "views":
        note = "Each post's current view count is placed on the day it was published."
    elif metric in ("views_total", "views_gained"):
        first = snaps[0].day.isoformat() if snaps else "today"
        note = (f"Views gained = lifetime views at the end of each period minus the end of the period before. "
                f"The CRM started saving one lifetime-views reading per day on {first}, so earlier periods are blank."
                if metric == "views_gained" else
                f"One reading saved per day since {first}.")
    elif metric == "open_pipeline":
        note = "Rebuilt from when deals were created and closed, using each deal's current value."
    return {
        "metric": metric, "label": label, "kind": kind, "format": fmt, "bucket": bucket,
        "start": start.isoformat(), "end": end.isoformat(), "points": points,
        "total": round(sum(vals), 2) if kind == "sum" else None,
        "latest": vals[-1] if vals else None, "note": note,
    }

"""Orders pulled from store integrations (Square), with full details."""
import csv
import io
import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..models import Order

router = APIRouter(prefix="/api/orders", tags=["orders"], dependencies=[Depends(current_user)])

SUMMARY_FIELDS = ["id", "source", "external_id", "channel_id", "contact_id", "deal_id", "location_id", "location_name",
                  "reference", "state", "source_name", "customer_name", "customer_email", "customer_phone", "currency",
                  "subtotal", "discount_total", "tax_total", "tip_total", "service_charge_total", "total", "refunded",
                  "net", "processing_fee", "item_count", "items_summary", "fulfillment_type", "fulfillment_state",
                  "payment_summary", "receipt_url", "ordered_at", "updated_at_ext", "closed_at", "synced_at"]


def _row(o: Order) -> dict:
    d = {f: getattr(o, f) for f in SUMMARY_FIELDS}
    for k in ("ordered_at", "updated_at_ext", "closed_at", "synced_at"):
        d[k] = d[k].isoformat() if d[k] else None
    d["channel_name"] = o.channel.name if o.channel else None
    return d


def _filtered(q, state, channel_id, date_from, date_to, fulfillment):
    stmt = select(Order)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Order.reference.ilike(like), Order.customer_name.ilike(like), Order.customer_email.ilike(like),
                              Order.items_summary.ilike(like), Order.external_id.ilike(like), Order.customer_phone.ilike(like)))
    if state:
        stmt = stmt.where(Order.state == state.upper())
    if channel_id:
        stmt = stmt.where(Order.channel_id == channel_id)
    if fulfillment:
        stmt = stmt.where(Order.fulfillment_type == fulfillment.upper())
    if date_from:
        stmt = stmt.where(Order.ordered_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(Order.ordered_at < datetime.combine(date_to + timedelta(days=1), time.min))
    return stmt


@router.get("")
def list_orders(q: str | None = None, state: str | None = None, channel_id: int | None = None,
                date_from: date | None = None, date_to: date | None = None, fulfillment: str | None = None,
                limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = _filtered(q, state, channel_id, date_from, date_to, fulfillment)
    sub = stmt.subquery()
    agg = db.execute(select(func.count(), func.coalesce(func.sum(sub.c.total), 0), func.coalesce(func.sum(sub.c.refunded), 0),
                            func.coalesce(func.sum(sub.c.net), 0), func.coalesce(func.sum(sub.c.processing_fee), 0),
                            func.coalesce(func.sum(sub.c.tax_total), 0), func.coalesce(func.sum(sub.c.tip_total), 0))
                     .select_from(sub)).one()
    count = int(agg[0])
    items = db.scalars(stmt.order_by(Order.ordered_at.desc().nulls_last(), Order.id.desc()).limit(limit).offset(offset)).all()
    return {"items": [_row(o) for o in items], "total": count, "summary": {
        "orders": count, "gross": round(agg[1], 2), "refunded": round(agg[2], 2), "net": round(agg[3], 2),
        "fees": round(agg[4], 2), "tax": round(agg[5], 2), "tips": round(agg[6], 2),
        "average": round(agg[3] / count, 2) if count else 0}}


@router.get("/export.csv")
def export_orders(q: str | None = None, state: str | None = None, channel_id: int | None = None,
                  date_from: date | None = None, date_to: date | None = None, fulfillment: str | None = None,
                  db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = [f for f in SUMMARY_FIELDS if f not in ("channel_id", "contact_id", "deal_id", "location_id")]
    w.writerow(cols)
    for o in db.scalars(_filtered(q, state, channel_id, date_from, date_to, fulfillment).order_by(Order.ordered_at.desc())):
        r = _row(o)
        w.writerow([r[c] for c in cols])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=orders.csv"})


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    o = get_or_404(db, Order, order_id)
    return {**_row(o), "raw": json.loads(o.raw or "{}"), "payments": json.loads(o.payments or "[]")}

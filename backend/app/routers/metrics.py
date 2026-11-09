"""Channel data: everything each channel's API (and the CRM) knows, what you chose to show,
and the dashboard's combined totals per channel type."""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import metrics
from ..database import get_db
from ..deps import current_user
from ..models import Channel
from .dashboard import _period

router = APIRouter(prefix="/api/metrics", tags=["metrics"], dependencies=[Depends(current_user)])


def _bounds(start: date | None, end: date | None, tz_offset: int):
    if start and end and start > end:
        raise HTTPException(422, "Start date is after end date")
    return _period(start, end, tz_offset)


@router.get("/channels")
def channel_list(start: date | None = None, end: date | None = None,
                 tz_offset: int = Query(0, ge=-840, le=840), db: Session = Depends(get_db)):
    lo, hi = _bounds(start, end, tz_offset)
    return metrics.all_channels(db, lo, hi)


@router.get("/channels/{channel_id}")
def channel_one(channel_id: int, start: date | None = None, end: date | None = None,
                tz_offset: int = Query(0, ge=-840, le=840), db: Session = Depends(get_db)):
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "Channel not found")
    lo, hi = _bounds(start, end, tz_offset)
    return metrics.channel_metrics(db, ch, lo, hi)


class DisplayIn(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=200)
    reset: bool = False


@router.put("/channels/{channel_id}/display")
def set_display(channel_id: int, body: DisplayIn, db: Session = Depends(get_db)):
    ch = db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "Channel not found")
    if body.reset:
        ch.display_metrics = ""
    else:
        seen, keys = set(), []
        for k in body.keys:
            k = k.strip()[:80]
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
        ch.display_metrics = json.dumps(keys)
    db.commit()
    shown, is_default = metrics.display_keys(ch)
    return {"display": shown, "is_default": is_default}


@router.get("/combined")
def combined(start: date | None = None, end: date | None = None,
             tz_offset: int = Query(0, ge=-840, le=840), db: Session = Depends(get_db)):
    lo, hi = _bounds(start, end, tz_offset)
    return metrics.combined(db, lo, hi)

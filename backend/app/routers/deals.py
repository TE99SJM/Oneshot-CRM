from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, ensure_exists, get_or_404
from ..models import Channel, Contact, Deal, Funnel, FunnelStage, utcnow
from ..schemas import DealIn, DealOut, DealPatch

router = APIRouter(prefix="/api/deals", tags=["deals"], dependencies=[Depends(current_user)])


def _apply_stage(deal: Deal, stage: FunnelStage) -> None:
    """Move a deal into a stage, keeping funnel, status and closed_at consistent."""
    deal.stage_id = stage.id
    deal.funnel_id = stage.funnel_id
    if stage.kind != deal.status:
        deal.closed_at = utcnow() if stage.kind in ("won", "lost") else None
    deal.status = stage.kind


@router.get("", response_model=list[DealOut])
def list_deals(funnel_id: int | None = None, status: str | None = None, contact_id: int | None = None,
               channel_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Deal)
    if funnel_id:
        stmt = stmt.where(Deal.funnel_id == funnel_id)
    if status:
        stmt = stmt.where(Deal.status == status)
    if contact_id:
        stmt = stmt.where(Deal.contact_id == contact_id)
    if channel_id:
        stmt = stmt.where(Deal.channel_id == channel_id)
    return db.scalars(stmt.order_by(Deal.updated_at.desc())).all()


@router.post("", response_model=DealOut, status_code=201)
def create_deal(data: DealIn, db: Session = Depends(get_db)):
    get_or_404(db, Funnel, data.funnel_id)
    stage = get_or_404(db, FunnelStage, data.stage_id, "Stage")
    if stage.funnel_id != data.funnel_id:
        raise HTTPException(422, "Stage does not belong to that funnel")
    ensure_exists(db, Contact, data.contact_id, "Contact")
    ensure_exists(db, Channel, data.channel_id, "Channel")
    deal = Deal(**data.model_dump(exclude={"stage_id", "funnel_id"}), status="open")
    _apply_stage(deal, stage)
    db.add(deal)
    db.commit()
    return deal


@router.get("/{deal_id}", response_model=DealOut)
def get_deal(deal_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Deal, deal_id)


@router.patch("/{deal_id}", response_model=DealOut)
def update_deal(deal_id: int, data: DealPatch, db: Session = Depends(get_db)):
    deal = get_or_404(db, Deal, deal_id)
    changes = data.model_dump(exclude_unset=True)
    if "contact_id" in changes:
        ensure_exists(db, Contact, changes["contact_id"], "Contact")
    if "channel_id" in changes:
        ensure_exists(db, Channel, changes["channel_id"], "Channel")
    stage_id = changes.pop("stage_id", None)
    if stage_id is not None:
        _apply_stage(deal, get_or_404(db, FunnelStage, stage_id, "Stage"))
    for k, v in changes.items():
        setattr(deal, k, v)
    db.commit()
    return deal


@router.delete("/{deal_id}", status_code=204)
def delete_deal(deal_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Deal, deal_id))
    db.commit()

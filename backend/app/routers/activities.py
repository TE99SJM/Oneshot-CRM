from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, ensure_exists, get_or_404
from ..models import Activity, Contact, Deal
from ..schemas import ActivityIn, ActivityOut, ActivityPatch

router = APIRouter(prefix="/api/activities", tags=["activities"], dependencies=[Depends(current_user)])


@router.get("", response_model=list[ActivityOut])
def list_activities(contact_id: int | None = None, deal_id: int | None = None, kind: str | None = None,
                    open_tasks: bool = False, limit: int = 100, db: Session = Depends(get_db)):
    stmt = select(Activity)
    if contact_id:
        stmt = stmt.where(Activity.contact_id == contact_id)
    if deal_id:
        stmt = stmt.where(Activity.deal_id == deal_id)
    if kind:
        stmt = stmt.where(Activity.kind == kind)
    if open_tasks:
        stmt = stmt.where(Activity.kind == "task", Activity.done.is_(False))
        stmt = stmt.order_by(Activity.due_at.is_(None), Activity.due_at)
    else:
        stmt = stmt.order_by(Activity.created_at.desc())
    return db.scalars(stmt.limit(min(limit, 500))).all()


@router.post("", response_model=ActivityOut, status_code=201)
def create_activity(data: ActivityIn, db: Session = Depends(get_db)):
    ensure_exists(db, Contact, data.contact_id, "Contact")
    ensure_exists(db, Deal, data.deal_id, "Deal")
    a = Activity(**data.model_dump())
    db.add(a)
    db.commit()
    return a


@router.patch("/{activity_id}", response_model=ActivityOut)
def update_activity(activity_id: int, data: ActivityPatch, db: Session = Depends(get_db)):
    a = get_or_404(db, Activity, activity_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    db.commit()
    return a


@router.delete("/{activity_id}", status_code=204)
def delete_activity(activity_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Activity, activity_id))
    db.commit()

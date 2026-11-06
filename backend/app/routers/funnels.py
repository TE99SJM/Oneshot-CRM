from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import current_user, get_or_404
from ..models import Deal, Funnel, FunnelStage
from ..schemas import FunnelIn, FunnelOut, StageIn

router = APIRouter(prefix="/api/funnels", tags=["funnels"], dependencies=[Depends(current_user)])

DEFAULT_STAGES = [
    StageIn(name="Awareness", probability=5),
    StageIn(name="Interest", probability=15),
    StageIn(name="Consideration", probability=35),
    StageIn(name="Intent", probability=60),
    StageIn(name="Won", probability=100, kind="won"),
    StageIn(name="Lost", probability=0, kind="lost"),
]


def _validate_stages(stages: list[StageIn]) -> None:
    if not stages:
        raise HTTPException(422, "A funnel needs at least one stage")
    if not any(s.kind == "open" for s in stages):
        raise HTTPException(422, "A funnel needs at least one open stage")


@router.get("", response_model=list[FunnelOut])
def list_funnels(db: Session = Depends(get_db)):
    return db.scalars(select(Funnel).options(selectinload(Funnel.stages)).order_by(Funnel.id)).all()


@router.post("", response_model=FunnelOut, status_code=201)
def create_funnel(data: FunnelIn, db: Session = Depends(get_db)):
    stages = data.stages if data.stages is not None else DEFAULT_STAGES
    _validate_stages(stages)
    f = Funnel(name=data.name, description=data.description)
    f.stages = [FunnelStage(name=s.name, probability=s.probability, kind=s.kind, position=i)
                for i, s in enumerate(stages)]
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@router.get("/{funnel_id}", response_model=FunnelOut)
def get_funnel(funnel_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Funnel, funnel_id)


@router.put("/{funnel_id}", response_model=FunnelOut)
def update_funnel(funnel_id: int, data: FunnelIn, db: Session = Depends(get_db)):
    """Rename a funnel and optionally replace its ordered stage list.

    Stages with an ``id`` are updated, stages without one are created, and omitted stages are
    deleted - but only if no deals are sitting in them.
    """
    f = get_or_404(db, Funnel, funnel_id)
    f.name, f.description = data.name, data.description
    if data.stages is not None:
        _validate_stages(data.stages)
        existing = {s.id: s for s in f.stages}
        keep_ids = {s.id for s in data.stages if s.id is not None}
        unknown = keep_ids - existing.keys()
        if unknown:
            raise HTTPException(422, f"Stage ids {sorted(unknown)} do not belong to this funnel")
        removed = [s for sid, s in existing.items() if sid not in keep_ids]
        for s in removed:
            used = db.scalar(select(func.count(Deal.id)).where(Deal.stage_id == s.id))
            if used:
                raise HTTPException(409, f"Stage '{s.name}' still has {used} deal(s); move them first")
        new_list = []
        for i, s in enumerate(data.stages):
            stage = existing[s.id] if s.id is not None else FunnelStage()
            stage.name, stage.probability, stage.kind, stage.position = s.name, s.probability, s.kind, i
            new_list.append(stage)
        f.stages = new_list  # delete-orphan removes dropped stages
        # Keep deal status in sync with any stage kind changes.
        for stage in new_list:
            if stage.id:
                for d in db.scalars(select(Deal).where(Deal.stage_id == stage.id)):
                    d.status = stage.kind
    db.commit()
    db.refresh(f)
    return f


@router.delete("/{funnel_id}", status_code=204)
def delete_funnel(funnel_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Funnel, funnel_id))
    db.commit()

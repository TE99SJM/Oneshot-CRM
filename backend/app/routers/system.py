from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import current_user
from ..seed import has_business_data, seed_demo

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.post("/demo/seed", dependencies=[Depends(current_user)])
def demo_seed(db: Session = Depends(get_db)):
    if not settings.allow_demo_seed:
        raise HTTPException(403, "Demo seeding is disabled (ALLOW_DEMO_SEED=false)")
    if has_business_data(db):
        raise HTTPException(409, "Demo data can only be loaded into an empty CRM")
    return seed_demo(db)

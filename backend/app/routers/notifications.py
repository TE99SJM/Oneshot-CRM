"""Order alerts settings + test button."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import notifications as alerts
from ..database import get_db
from ..deps import current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(current_user)])


class AlertSettingsIn(BaseModel):
    config: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)       # blank values keep what's saved
    clear_secrets: list[str] = Field(default_factory=list)


class TestIn(BaseModel):
    channel: str | None = None                          # push | twilio | email; None = every turned-on one


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    data = alerts.public(db)
    db.commit()                                         # first visit creates the row + private topic
    return data


@router.put("")
def put_settings(body: AlertSettingsIn, db: Session = Depends(get_db)):
    return alerts.save(db, body.config, body.secrets, body.clear_secrets)


@router.post("/test")
def test(body: TestIn, db: Session = Depends(get_db)):
    only = body.channel if body.channel in alerts.CHANNELS else None
    results = alerts.send_test(db, only)
    return {"ok": bool(results) and all(v == "ok" for v in results.values()), "results": results}

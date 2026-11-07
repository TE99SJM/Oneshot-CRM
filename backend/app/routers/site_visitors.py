"""Independent website cards on the existing dashboard."""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..integrations import base, google_analytics
from ..integrations.crypto import decrypt_secrets
from ..models import Integration

router = APIRouter(prefix="/api/dashboard/site-visitors", tags=["dashboard"], dependencies=[Depends(current_user)])


@router.get("")
def sites(db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name, "hostname": json.loads(i.config).get("hostname", ""), "enabled": i.enabled}
            for i in db.scalars(select(Integration).where(Integration.provider == "google_analytics").order_by(Integration.id))]


@router.get("/{integration_id}")
def site_report(integration_id: int, start: date | None = None, end: date | None = None,
                refresh: bool = False, db: Session = Depends(get_db)):
    integ = get_or_404(db, Integration, integration_id)
    if integ.provider != "google_analytics":
        raise HTTPException(404, "Site connection not found")
    if not integ.enabled:
        raise HTTPException(409, "This site's analytics connection is paused. Enable it in Integrations.")
    if start and end and start > end:
        raise HTTPException(422, "Start date is after end date")
    if start and start.isoformat() < google_analytics.ALL_TIME_START:
        raise HTTPException(422, "Select a date on or after August 14, 2015")
    try:
        secrets = decrypt_secrets(integ.secrets)
    except ValueError as e:
        raise HTTPException(422, "The saved analytics key cannot be read. Upload it again in Integrations.") from e
    try:
        with base.make_client() as client:
            return google_analytics.report(client, json.loads(integ.config), secrets,
                                           start.isoformat() if start else google_analytics.ALL_TIME_START,
                                           end.isoformat() if end else "today", refresh)
    except base.SyncError as e:
        raise HTTPException(502, str(e)) from e

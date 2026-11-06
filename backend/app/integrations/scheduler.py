"""Background loop that syncs enabled integrations when they're due."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from ..database import SessionLocal
from ..models import Integration, utcnow
from .service import run_sync

log = logging.getLogger("oneshot.sync")


_last_attempt: dict[int, object] = {}   # integration id -> last attempt time (in memory)
RETRY_AFTER_ERROR = timedelta(minutes=30)


def _run_due() -> None:
    with SessionLocal() as db:
        now = utcnow()
        for integ in db.scalars(select(Integration).where(Integration.enabled.is_(True))).all():
            if integ.sync_interval_minutes <= 0 or integ.last_status == "running":
                continue
            interval = timedelta(minutes=integ.sync_interval_minutes)
            if integ.last_sync_at and integ.last_sync_at + interval > now:
                continue
            attempted = _last_attempt.get(integ.id)
            if attempted and attempted + min(interval, RETRY_AFTER_ERROR) > now:
                continue
            _last_attempt[integ.id] = now
            try:
                result = run_sync(db, integ)
                log.info("sync %s #%s -> %s %s", integ.provider, integ.id, result.last_status, result.last_error)
            except Exception:  # pragma: no cover
                log.exception("sync failed")


async def scheduler_loop(interval_seconds: int = 60) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            await asyncio.to_thread(_run_due)
        except Exception:  # pragma: no cover
            log.exception("scheduler error")
        await asyncio.sleep(interval_seconds)

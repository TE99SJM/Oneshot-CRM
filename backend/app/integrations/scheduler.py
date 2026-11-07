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
        try:
            from ..stats_history import record_snapshots
            record_snapshots(db)
        except Exception:  # pragma: no cover
            log.exception("snapshot failed")


async def scheduler_loop(interval_seconds: int = 60) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            await asyncio.to_thread(_run_due)
        except Exception:  # pragma: no cover
            log.exception("scheduler error")
        await asyncio.sleep(interval_seconds)


async def publish_loop(interval_seconds: int = 30) -> None:
    """Separate from syncs so a long sync never delays a scheduled post."""
    from ..publishing.runner import run_due
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(run_due)
        except Exception:  # pragma: no cover
            log.exception("publish scheduler error")
        await asyncio.sleep(interval_seconds)


def run_message_checks() -> None:
    """Frequent buyer-chat check for TikTok Shop, separate from the (6-hourly) full sync."""
    import json
    from . import tiktok_shop
    with SessionLocal() as db:
        now = utcnow()
        for integ in db.scalars(select(Integration).where(Integration.enabled.is_(True),
                                                          Integration.provider == "tiktok_shop")).all():
            if integ.last_status == "running":
                continue
            if not tiktok_shop.message_check_due(json.loads(integ.config or "{}"), now):
                continue
            result = tiktok_shop.check_messages(db, integ)
            log.info("messages %s #%s -> %s", integ.provider, integ.id, result)


async def messages_loop(interval_seconds: int = 60) -> None:
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.to_thread(run_message_checks)
        except Exception:  # pragma: no cover
            log.exception("message check error")
        await asyncio.sleep(interval_seconds)

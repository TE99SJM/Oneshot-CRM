"""Background loop that syncs enabled integrations when they're due."""
import asyncio
import json
import logging
import os
import threading
from datetime import timedelta

from sqlalchemy import select

from ..database import SessionLocal
from ..models import Integration, utcnow
from .service import run_sync

log = logging.getLogger("oneshot.sync")


_last_attempt: dict[int, object] = {}   # integration id -> last automatic attempt (in memory)
RETRY_AFTER_ERROR = timedelta(minutes=30)
STALE_AFTER = timedelta(minutes=5)        # a lane that hasn't ticked for this long is reported as stuck
OPEN_COOLDOWN = timedelta(minutes=1)      # opening several tabs must not spend provider quota repeatedly

# Two independent lanes so a slow stats sync (YouTube, Rumble, Twitch…) never delays sales/messages and
# a stuck sales sync never stops follower/view updates.
LANES = ("sales", "stats")
_lane_locks = {lane: threading.Lock() for lane in LANES}
_browser_lock = threading.Lock()
_state: dict = {"enabled": False, "started_at": None,
                **{lane: {"last_tick": None, "running_id": None, "running_name": "", "running_since": None}
                   for lane in LANES}}


def lane_of(provider: str) -> str:
    from .registry import PROVIDERS
    info = PROVIDERS[provider].INFO if provider in PROVIDERS else None
    return "sales" if info and info.default_interval < 360 else "stats"


def next_sync_at(integ: Integration, now=None):
    """When the scheduler will next pick this connection up (None = manual only / paused)."""
    if not integ.enabled or integ.sync_interval_minutes <= 0:
        return None
    interval = timedelta(minutes=integ.sync_interval_minutes)
    due = integ.last_sync_at + interval if integ.last_sync_at else (now or utcnow())
    attempted = _last_attempt.get(integ.id)
    if attempted:
        due = max(due, attempted + min(interval, RETRY_AFTER_ERROR))
    return due


def _eligible(integ: Integration, now, on_open: bool = False) -> bool:
    if not integ.enabled or integ.sync_interval_minutes <= 0 or integ.last_status == "running":
        return False
    if on_open:
        if not json.loads(integ.config or "{}").get("sync_on_open", True):
            return False
        if integ.last_sync_at and now - integ.last_sync_at < OPEN_COOLDOWN:
            return False
        attempted = _last_attempt.get(integ.id)
        cooldown = min(timedelta(minutes=integ.sync_interval_minutes), RETRY_AFTER_ERROR) \
            if integ.last_status == "error" else OPEN_COOLDOWN
        return not attempted or now - attempted >= cooldown
    nxt = next_sync_at(integ, now)
    return nxt is not None and nxt <= now


def _claim(integ: Integration, on_open: bool) -> bool:
    """Called under the per-connection sync lock, after reloading its latest saved state."""
    now = utcnow()
    if not _eligible(integ, now, on_open):
        return False
    _last_attempt[integ.id] = now
    return True


def _due_ids(lane: str, on_open: bool = False) -> list[int]:
    now = utcnow()
    with SessionLocal() as db:
        out = []
        for integ in db.scalars(select(Integration).where(Integration.enabled.is_(True))).all():
            if lane_of(integ.provider) == lane and _eligible(integ, now, on_open):
                out.append(integ.id)
        return out


def _run_due(lane: str | None = None, on_open: bool = False) -> None:
    for ln in ([lane] if lane else LANES):
        with _lane_locks[ln]:
            _run_lane(ln, on_open)


def _run_lane(ln: str, on_open: bool) -> None:
    st = _state[ln]
    st["last_tick"] = utcnow()
    for iid in _due_ids(ln, on_open):
        with SessionLocal() as db:          # fresh session per connection: one failure can't spoil the rest
            integ = db.get(Integration, iid)
            if integ is None:
                continue
            st.update(running_id=iid, running_name=integ.name, running_since=utcnow())
            try:
                result = run_sync(db, integ, should_sync=lambda fresh: _claim(fresh, on_open))
                log.info("auto-sync %s #%s (%s) -> %s %s", integ.provider, iid, integ.name,
                         result.last_status, result.last_error)
            except Exception:  # pragma: no cover
                log.exception("auto-sync %s #%s failed", integ.provider, iid)
            finally:
                st.update(running_id=None, running_name="", running_since=None, last_tick=utcnow())
    if ln == "stats":
        try:
            from ..stats_history import record_snapshots
            with SessionLocal() as db:
                record_snapshots(db)
        except Exception:  # pragma: no cover
            log.exception("snapshot failed")


def request_browser_sync() -> bool:
    # Respect the server-wide automatic-sync switch as well as each connection's preferences.
    if os.getenv("SYNC_SCHEDULER", "true").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return _browser_lock.acquire(blocking=False)


async def run_browser_sync() -> None:
    try:
        # Keep the usual two lanes: a long video sync must not hold up orders or mail.
        results = await asyncio.gather(*(asyncio.to_thread(_run_due, lane, True) for lane in LANES),
                                       return_exceptions=True)
        for lane, result in zip(LANES, results):
            if isinstance(result, BaseException):
                log.error("browser-open sync failed (%s): %s", lane, result)
    finally:
        _browser_lock.release()


def status() -> dict:
    now = utcnow()
    lanes = {}
    for ln in LANES:
        st = _state[ln]
        tick = st["last_tick"]
        busy_for = (now - st["running_since"]).total_seconds() if st["running_since"] else None
        lanes[ln] = {"last_tick": tick.isoformat() if tick else None,
                     "running_id": st["running_id"], "running_name": st["running_name"],
                     "running_seconds": round(busy_for) if busy_for is not None else None,
                     "ok": bool(tick) and (busy_for is not None and busy_for < 3600 or now - tick < STALE_AFTER)}
    healthy = _state["enabled"] and all(v["ok"] for v in lanes.values())
    started = _state["started_at"]
    warming = bool(started) and now - started < timedelta(minutes=2)
    return {"enabled": _state["enabled"], "healthy": healthy or warming, "lanes": lanes,
            "started_at": started.isoformat() if started else None}


async def _lane_loop(lane: str, first_delay: int, interval_seconds: int) -> None:
    await asyncio.sleep(first_delay)
    while True:
        try:
            await asyncio.to_thread(_run_due, lane)
        except Exception:  # pragma: no cover
            log.exception("scheduler error (%s)", lane)
        await asyncio.sleep(interval_seconds)


async def scheduler_loop(interval_seconds: int = 60) -> None:
    _state["enabled"], _state["started_at"] = True, utcnow()
    log.info("automatic sync on: sales/messages lane + stats lane, checking every %ss", interval_seconds)
    await asyncio.gather(_lane_loop("sales", 10, interval_seconds), _lane_loop("stats", 15, interval_seconds))


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

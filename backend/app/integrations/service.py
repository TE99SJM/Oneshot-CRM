"""Run tests/syncs for an Integration, store results, and serialize them for the API."""
import json
import threading
from dataclasses import asdict

from sqlalchemy.orm import Session

from ..models import Channel, Integration, utcnow
from . import base
from .crypto import decrypt_secrets
from .registry import PROVIDERS

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(integration_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(integration_id, threading.Lock())


def provider_meta() -> list[dict]:
    return [asdict(m.INFO) for m in PROVIDERS.values()]


def ensure_channel(db: Session, integ: Integration) -> Channel:
    ch = db.get(Channel, integ.channel_id) if integ.channel_id else None
    if ch is None:
        info = PROVIDERS[integ.provider].INFO
        ch = Channel(name=integ.name or info.name, kind=info.channel_kind, platform=info.platform)
        db.add(ch)
        db.flush()
        integ.channel_id = ch.id
    return ch


def _context(db: Session, integ: Integration, client) -> base.SyncContext:
    return base.SyncContext(db=db, client=client, channel=ensure_channel(db, integ),
                            config=json.loads(integ.config or "{}"), secrets=decrypt_secrets(integ.secrets),
                            last_sync_at=integ.last_sync_at, integration_id=integ.id)


def test_integration(db: Session, integ: Integration) -> tuple[bool, str]:
    try:
        with base.make_client() as client:
            ctx = _context(db, integ, client)
            msg = PROVIDERS[integ.provider].test(ctx)
            db.commit()
            return True, msg
    except (base.SyncError, ValueError) as e:
        db.rollback()
        return False, str(e)
    except Exception as e:  # network errors etc.
        db.rollback()
        return False, f"{PROVIDERS[integ.provider].INFO.name}: {type(e).__name__}: {e}"


def update_total_views(db: Session, ctx: base.SyncContext) -> None:
    """Lifetime views for the channel: the platform's own total when the provider reports one
    (ctx.stats["total_views"]), otherwise the sum of every synced post's current views."""
    from sqlalchemy import func, select
    from ..models import Post
    summed = int(db.scalar(select(func.coalesce(func.sum(Post.views), 0)).where(Post.channel_id == ctx.channel.id)) or 0)
    reported = ctx.stats.get("total_views")
    total = max(int(reported), summed) if reported is not None else summed
    ctx.channel.total_views = total
    if total or reported is not None or ctx.channel.kind == "social":
        ctx.stats["total_views"] = total          # stores with no videos don't show "0 lifetime views"


def run_sync(db: Session, integ: Integration) -> Integration:
    lock = _lock(integ.id)
    if not lock.acquire(blocking=False):
        raise base.SyncError("A sync for this connection is already running")
    try:
        integ.last_status = "running"
        db.commit()
        started = utcnow()
        had_synced = integ.last_sync_at is not None     # the very first sync imports history: no alerts
        from .. import notifications
        before_id = notifications.max_order_id(db)
        try:
            with base.make_client() as client:
                ctx = _context(db, integ, client)
                PROVIDERS[integ.provider].sync(ctx)
                db.flush()
                update_total_views(db, ctx)
            integ.last_status, integ.last_error = "ok", ""
            integ.last_sync_at = started
            integ.last_result = json.dumps({**ctx.stats, "warnings": ctx.warnings,
                                            "seconds": round((utcnow() - started).total_seconds(), 1)})
            db.commit()
            if had_synced:
                try:
                    notifications.order_alerts(db, before_id, integ.channel_id)
                except Exception:  # an alert problem must never mark the sync as failed
                    notifications.log.exception("order alerts failed")
                    db.rollback()
        except Exception as e:
            db.rollback()
            integ = db.get(Integration, integ.id)
            integ.last_status = "error"
            integ.last_error = str(e) if isinstance(e, (base.SyncError, ValueError)) else \
                f"{PROVIDERS[integ.provider].INFO.name}: {type(e).__name__}: {e}"
            db.commit()
        return integ
    finally:
        lock.release()


def _next(integ: Integration) -> str | None:
    from .scheduler import next_sync_at
    n = next_sync_at(integ)
    return n.isoformat() if n else None


def serialize(integ: Integration) -> dict:
    try:
        secret_keys = sorted(decrypt_secrets(integ.secrets).keys())
        secrets_ok = True
    except ValueError:
        secret_keys, secrets_ok = [], False
    return {
        "id": integ.id, "provider": integ.provider, "name": integ.name, "channel_id": integ.channel_id,
        "channel_name": integ.channel.name if integ.channel else None,
        "config": json.loads(integ.config or "{}"), "saved_secrets": secret_keys, "secrets_ok": secrets_ok,
        "enabled": integ.enabled, "sync_interval_minutes": integ.sync_interval_minutes,
        "last_sync_at": integ.last_sync_at.isoformat() if integ.last_sync_at else None,
        "next_sync_at": _next(integ),
        "last_status": integ.last_status, "last_error": integ.last_error,
        "last_result": json.loads(integ.last_result or "{}"), "created_at": integ.created_at.isoformat(),
    }

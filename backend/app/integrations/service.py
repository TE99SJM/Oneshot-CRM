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
                            last_sync_at=integ.last_sync_at)


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


def run_sync(db: Session, integ: Integration) -> Integration:
    lock = _lock(integ.id)
    if not lock.acquire(blocking=False):
        raise base.SyncError("A sync for this connection is already running")
    try:
        integ.last_status = "running"
        db.commit()
        started = utcnow()
        try:
            with base.make_client() as client:
                ctx = _context(db, integ, client)
                PROVIDERS[integ.provider].sync(ctx)
                db.flush()
            integ.last_status, integ.last_error = "ok", ""
            integ.last_sync_at = started
            integ.last_result = json.dumps({**ctx.stats, "warnings": ctx.warnings,
                                            "seconds": round((utcnow() - started).total_seconds(), 1)})
            db.commit()
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
        "last_status": integ.last_status, "last_error": integ.last_error,
        "last_result": json.loads(integ.last_result or "{}"), "created_at": integ.created_at.isoformat(),
    }

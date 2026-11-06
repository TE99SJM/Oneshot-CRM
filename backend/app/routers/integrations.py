"""Connect external platforms (YouTube, Facebook Page, Square, Rumble) and sync their data."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..integrations.base import SyncError
from ..integrations.crypto import decrypt_secrets, encrypt_secrets
from ..integrations.registry import PROVIDERS
from ..integrations.service import ensure_channel, provider_meta, run_sync, serialize, test_integration
from ..models import Channel, Integration

router = APIRouter(prefix="/api/integrations", tags=["integrations"], dependencies=[Depends(current_user)])


class IntegrationIn(BaseModel):
    provider: str
    name: str = Field(default="", max_length=120)
    channel_id: int | None = None
    values: dict[str, str] = {}          # field key -> value (secret and non-secret)
    enabled: bool = True
    sync_interval_minutes: int = Field(default=360, ge=0, le=60 * 24 * 7)


class IntegrationPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    channel_id: int | None = None
    values: dict[str, str] | None = None  # empty secret values keep the saved secret
    enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 7)


def _split(provider: str, values: dict[str, str], old_config: dict, old_secrets: dict) -> tuple[dict, dict]:
    info = PROVIDERS[provider].INFO
    config, secrets = dict(old_config), dict(old_secrets)
    for f in info.fields:
        if f.key not in values:
            if f.key not in config and not f.secret and f.default:
                config[f.key] = f.default
            continue
        v = (values[f.key] or "").strip()
        if f.secret:
            if v:
                secrets[f.key] = v
        else:
            config[f.key] = v or f.default
    for f in info.fields:
        present = secrets.get(f.key) if f.secret else config.get(f.key)
        if f.required and not present:
            raise HTTPException(422, f"{f.label} is required")
    return config, secrets


@router.get("/providers")
def providers():
    return provider_meta()


@router.get("")
def list_integrations(db: Session = Depends(get_db)):
    return [serialize(i) for i in db.scalars(select(Integration).order_by(Integration.id)).all()]


@router.post("", status_code=201)
def create_integration(data: IntegrationIn, db: Session = Depends(get_db)):
    if data.provider not in PROVIDERS:
        raise HTTPException(422, f"Unknown provider '{data.provider}'")
    if data.channel_id is not None and db.get(Channel, data.channel_id) is None:
        raise HTTPException(422, "Channel not found")
    config, secrets = _split(data.provider, data.values, {}, {})
    integ = Integration(provider=data.provider, name=data.name or PROVIDERS[data.provider].INFO.name,
                        channel_id=data.channel_id, config=json.dumps(config), secrets=encrypt_secrets(secrets),
                        enabled=data.enabled, sync_interval_minutes=data.sync_interval_minutes)
    db.add(integ)
    db.flush()
    ensure_channel(db, integ)
    db.commit()
    db.refresh(integ)
    return serialize(integ)


@router.get("/{integration_id}")
def get_integration(integration_id: int, db: Session = Depends(get_db)):
    return serialize(get_or_404(db, Integration, integration_id))


@router.patch("/{integration_id}")
def update_integration(integration_id: int, data: IntegrationPatch, db: Session = Depends(get_db)):
    integ = get_or_404(db, Integration, integration_id)
    patch = data.model_dump(exclude_unset=True)
    if "values" in patch and patch["values"] is not None:
        try:
            old_secrets = decrypt_secrets(integ.secrets)
        except ValueError:
            old_secrets = {}
        config, secrets = _split(integ.provider, patch["values"], json.loads(integ.config or "{}"), old_secrets)
        integ.config, integ.secrets = json.dumps(config), encrypt_secrets(secrets)
    if "channel_id" in patch:
        if patch["channel_id"] is not None and db.get(Channel, patch["channel_id"]) is None:
            raise HTTPException(422, "Channel not found")
        integ.channel_id = patch["channel_id"]
    for k in ("name", "enabled", "sync_interval_minutes"):
        if patch.get(k) is not None:
            setattr(integ, k, patch[k])
    ensure_channel(db, integ)
    db.commit()
    db.refresh(integ)
    return serialize(integ)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(integration_id: int, db: Session = Depends(get_db)):
    """Disconnect. Synced contacts, deals and posts stay in the CRM."""
    db.delete(get_or_404(db, Integration, integration_id))
    db.commit()


@router.post("/{integration_id}/test")
def test(integration_id: int, db: Session = Depends(get_db)):
    ok, message = test_integration(db, get_or_404(db, Integration, integration_id))
    return {"ok": ok, "message": message}


@router.post("/{integration_id}/sync")
async def sync_now(integration_id: int, db: Session = Depends(get_db)):
    integ = get_or_404(db, Integration, integration_id)
    try:
        integ = await asyncio.to_thread(run_sync, db, integ)
    except SyncError as e:
        raise HTTPException(409, str(e)) from e
    db.refresh(integ)
    return serialize(integ)

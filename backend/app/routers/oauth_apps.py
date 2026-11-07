"""Sign-in for TikTok and TikTok Shop connections (same pattern for any app listed in OAUTH_APPS).

Flow: save the return address → GET /authorize gives the platform's sign-in link → the platform sends the browser
to the public /api/oauth/<slug>/callback (see oauth_public.py) → we swap the code for tokens. If the automatic
return can't reach the CRM, paste the address from the browser bar into POST /connect instead.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..integrations import base
from ..integrations.base import SyncError
from ..integrations.crypto import decrypt_secrets, encrypt_secrets
from ..integrations.oauth_apps import extract_code, new_state, normalize_redirect, redirect_for
from ..integrations.registry import OAUTH_APPS
from ..integrations.service import serialize
from ..models import Integration

router = APIRouter(prefix="/api/integrations", tags=["integrations"], dependencies=[Depends(current_user)])


def _app(db: Session, integration_id: int) -> tuple[Integration, object]:
    integ = get_or_404(db, Integration, integration_id)
    mod = OAUTH_APPS.get(integ.provider)
    if mod is None:
        raise HTTPException(422, "This connection doesn't use sign-in")
    return integ, mod


def oauth_info(db: Session, integ: Integration, mod) -> dict:
    cfg, secrets = json.loads(integ.config or "{}"), decrypt_secrets(integ.secrets)
    return {**redirect_for(db, integ, mod.OAUTH_SLUG), "name": mod.OAUTH_NAME,
            "signed_in": bool(secrets.get("refresh_token") or secrets.get("access_token")),
            "account": cfg.get("oauth_account", ""), "missing_scopes": cfg.get("missing_scopes", ""),
            "redirect_in_link": integ.provider != "tiktok_shop"}


def finish_signin(db: Session, integ: Integration, code: str) -> Integration:
    mod = OAUTH_APPS[integ.provider]
    cfg, secrets = json.loads(integ.config or "{}"), decrypt_secrets(integ.secrets)
    if not code:
        raise SyncError(f"{mod.OAUTH_NAME}: no sign-in code found. Paste the whole address from the browser bar.")
    with base.make_client() as client:
        result = mod.exchange(client, cfg, secrets, code, cfg.get("oauth_redirect", ""))
    secrets.update(result.get("secrets") or {})
    secrets.pop("oauth_state", None)
    cfg.update(result.get("config") or {})
    cfg["oauth_account"] = result.get("account") or ""
    cfg.pop("oauth_return_to", None)
    if integ.provider == "tiktok_shop":           # new permissions may have come with this sign-in: check chats now
        for k in ("messages_status", "messages_error", "messages_checked_at"):
            cfg.pop(k, None)
    integ.secrets, integ.config = encrypt_secrets(secrets), json.dumps(cfg)
    integ.last_status, integ.last_error = "idle", ""
    db.commit()
    return integ


class RedirectIn(BaseModel):
    redirect_uri: str = Field(max_length=500)


class PasteIn(BaseModel):
    pasted: str = Field(min_length=1, max_length=4000)


@router.get("/{integration_id}/oauth")
def get_oauth(integration_id: int, db: Session = Depends(get_db)):
    integ, mod = _app(db, integration_id)
    return oauth_info(db, integ, mod)


@router.put("/{integration_id}/oauth/redirect")
def set_redirect(integration_id: int, data: RedirectIn, db: Session = Depends(get_db)):
    integ, mod = _app(db, integration_id)
    try:
        uri = normalize_redirect(data.redirect_uri, mod.OAUTH_SLUG)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    cfg = json.loads(integ.config or "{}")
    cfg["oauth_redirect"] = uri
    integ.config = json.dumps(cfg)
    db.commit()
    return oauth_info(db, integ, mod)


@router.get("/{integration_id}/oauth/authorize")
def authorize(integration_id: int, return_to: str = "", db: Session = Depends(get_db)):
    integ, mod = _app(db, integration_id)
    cfg, secrets = json.loads(integ.config or "{}"), decrypt_secrets(integ.secrets)
    if not cfg.get("oauth_redirect"):
        raise HTTPException(422, "Save the return address first (step 1).")
    state = new_state()
    secrets["oauth_state"] = state
    cfg["oauth_return_to"] = return_to.rstrip("/")[:300] if return_to.startswith(("http://", "https://")) else ""
    try:
        url = mod.authorize_url(cfg, secrets, cfg["oauth_redirect"], state)
    except SyncError as e:
        raise HTTPException(422, str(e)) from e
    integ.secrets, integ.config = encrypt_secrets(secrets), json.dumps(cfg)
    db.commit()
    return {"url": url}


@router.post("/{integration_id}/oauth/connect")
def connect_pasted(integration_id: int, data: PasteIn, db: Session = Depends(get_db)):
    integ, mod = _app(db, integration_id)
    code, _state = extract_code(data.pasted)
    try:
        finish_signin(db, integ, code)
    except SyncError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    return {"integration": serialize(integ), "oauth": oauth_info(db, integ, mod)}


@router.post("/{integration_id}/oauth/sign-out")
def sign_out(integration_id: int, db: Session = Depends(get_db)):
    integ, mod = _app(db, integration_id)
    secrets = decrypt_secrets(integ.secrets)
    for k in ("access_token", "refresh_token", "token_expires", "shop_cipher", "oauth_state", "open_id"):
        secrets.pop(k, None)
    integ.secrets = encrypt_secrets(secrets)
    db.commit()
    return {"integration": serialize(integ), "oauth": oauth_info(db, integ, mod)}

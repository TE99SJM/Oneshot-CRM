"""Connect external platforms (YouTube, Facebook Page, Square, Rumble) and sync their data."""
import asyncio
import json
import secrets as secrets_mod
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..integrations.base import SyncError
from ..integrations.crypto import decrypt_secrets, encrypt_secrets
from ..integrations import base, ebay, youtube
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
    sync_interval_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 7)   # None = provider default


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
    validate = getattr(PROVIDERS[provider], "validate_config", None)
    if validate:
        try:
            validate(config, secrets)
        except SyncError as e:
            raise HTTPException(422, str(e)) from e
    return config, secrets


@router.get("/providers")
def providers():
    return provider_meta()


@router.get("/scheduler")
def scheduler_status():
    """Is automatic syncing alive? Last tick of each lane and what it's syncing right now."""
    from ..integrations.scheduler import status
    return status()


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
    if data.provider == "ebay":
        config["verification_token"] = ebay.new_verification_token()
    integ = Integration(provider=data.provider, name=data.name or PROVIDERS[data.provider].INFO.name,
                        channel_id=data.channel_id, config=json.dumps(config), secrets=encrypt_secrets(secrets),
                        enabled=data.enabled,
                        sync_interval_minutes=data.sync_interval_minutes if data.sync_interval_minutes is not None
                        else PROVIDERS[data.provider].INFO.default_interval)
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


# ---------------------------------------------------------------- eBay sign-in (authorization code flow)
class EbayConnectIn(BaseModel):
    pasted: str = Field(min_length=1, max_length=4000)


def _ebay(db: Session, integration_id: int) -> Integration:
    integ = get_or_404(db, Integration, integration_id)
    if integ.provider != "ebay":
        raise HTTPException(422, "Not an eBay connection")
    return integ


@router.get("/{integration_id}/ebay/authorize")
def ebay_authorize(integration_id: int, db: Session = Depends(get_db)):
    integ = _ebay(db, integration_id)
    config = json.loads(integ.config or "{}")
    if not config.get("verification_token"):
        config["verification_token"] = ebay.new_verification_token()
        integ.config = json.dumps(config)
        db.commit()
    try:
        return {"url": ebay.authorize_url(integ.id, config)}
    except SyncError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/{integration_id}/ebay/connect")
def ebay_connect(integration_id: int, data: EbayConnectIn, db: Session = Depends(get_db)):
    from .ebay_public import finish_connect
    integ = _ebay(db, integration_id)
    try:
        finish_connect(db, integ, ebay.extract_code(data.pasted))
    except (SyncError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    db.refresh(integ)
    return serialize(integ)


# ---------------------------------------------------------------- YouTube posting sign-in (Google OAuth)
class YoutubeConnectIn(BaseModel):
    pasted: str = Field(min_length=1, max_length=4000)


class YoutubeRedirectIn(BaseModel):
    redirect_uri: str = Field(default="", max_length=500)   # "" = copy and paste (127.0.0.1)


def _youtube(db: Session, integration_id: int) -> Integration:
    integ = get_or_404(db, Integration, integration_id)
    if integ.provider != "youtube":
        raise HTTPException(422, "Not a YouTube connection")
    return integ


def youtube_redirect_options(db: Session, integ: Integration) -> dict:
    from ..publishing.runner import public_base
    config = json.loads(integ.config or "{}")
    base_url = public_base(db, None)        # e.g. the Tailscale Funnel host already used for eBay
    return {"saved": config.get("oauth_redirect_uri") or youtube.REDIRECT_URI,
            "loopback": youtube.REDIRECT_URI, "callback_path": youtube.CALLBACK_PATH,
            "suggested": f"{base_url}{youtube.CALLBACK_PATH}" if base_url else ""}


def finish_youtube_signin(db: Session, integ: Integration, code: str) -> Integration:
    """Swap the one-time code for a long-term token and remember which channel it posts to."""
    config, secrets = json.loads(integ.config or "{}"), decrypt_secrets(integ.secrets)
    if not secrets.get("pkce_verifier"):
        raise SyncError("YouTube: click “Open Google sign-in” first, then try again")
    redirect = secrets.get("pkce_redirect") or youtube.REDIRECT_URI
    with base.make_client() as client:
        tokens = youtube.exchange_code(client, config, secrets, code, secrets["pkce_verifier"], redirect)
        try:
            ch = youtube.my_channel(client, tokens["access_token"])
        except SyncError:
            ch = {}
    secrets["refresh_token"] = tokens["refresh_token"]
    for k in ("pkce_verifier", "pkce_redirect", "oauth_state", "oauth_return_to"):
        secrets.pop(k, None)
    config["upload_channel_title"] = (ch.get("snippet") or {}).get("title", "")
    config["upload_channel_id"] = ch.get("id", "")
    integ.config, integ.secrets = json.dumps(config), encrypt_secrets(secrets)
    db.commit()
    db.refresh(integ)
    return integ


@router.get("/{integration_id}/youtube/redirect")
def youtube_redirect_get(integration_id: int, db: Session = Depends(get_db)):
    return youtube_redirect_options(db, _youtube(db, integration_id))


@router.put("/{integration_id}/youtube/redirect")
def youtube_redirect_set(integration_id: int, data: YoutubeRedirectIn, db: Session = Depends(get_db)):
    integ = _youtube(db, integration_id)
    try:
        uri = youtube.normalize_redirect(data.redirect_uri)
    except SyncError as e:
        raise HTTPException(422, str(e)) from e
    config = json.loads(integ.config or "{}")
    if uri == youtube.REDIRECT_URI:
        config.pop("oauth_redirect_uri", None)
    else:
        config["oauth_redirect_uri"] = uri
    integ.config = json.dumps(config)
    db.commit()
    return youtube_redirect_options(db, integ)


@router.get("/{integration_id}/youtube/authorize")
def youtube_authorize(integration_id: int, return_to: str = "", db: Session = Depends(get_db)):
    """return_to: the CRM address in your browser (e.g. http://100.121.179.33:3050), where the automatic
    return sends you after Google."""
    integ = _youtube(db, integration_id)
    config = json.loads(integ.config or "{}")
    try:
        secrets = decrypt_secrets(integ.secrets)
    except ValueError as e:
        raise HTTPException(422, "Saved credentials can't be read; re-enter them with Edit") from e
    if not secrets.get("oauth_client_secret"):
        raise HTTPException(422, "Enter the OAuth client secret first (Edit the YouTube connection)")
    redirect = config.get("oauth_redirect_uri") or youtube.REDIRECT_URI
    verifier, challenge = youtube.new_pkce()
    state = f"yt{integ.id}.{secrets_mod.token_urlsafe(24)}"
    try:
        url = youtube.authorize_url(config, challenge, state=state, redirect_uri=redirect)
    except SyncError as e:
        raise HTTPException(422, str(e)) from e
    rt = urlparse(return_to.strip())
    secrets.update(pkce_verifier=verifier, pkce_redirect=redirect, oauth_state=state,
                   oauth_return_to=f"{rt.scheme}://{rt.netloc}" if rt.scheme in ("http", "https") and rt.netloc else "")
    integ.secrets = encrypt_secrets(secrets)
    db.commit()
    return {"url": url, "redirect_uri": redirect, "automatic": redirect != youtube.REDIRECT_URI}


@router.post("/{integration_id}/youtube/connect")
def youtube_connect(integration_id: int, data: YoutubeConnectIn, db: Session = Depends(get_db)):
    integ = _youtube(db, integration_id)
    try:
        code = youtube.extract_code(data.pasted)
        integ = finish_youtube_signin(db, integ, code)
    except SyncError as e:
        raise HTTPException(422, str(e)) from e
    return serialize(integ)


@router.post("/{integration_id}/youtube/disconnect")
def youtube_disconnect(integration_id: int, db: Session = Depends(get_db)):
    integ = _youtube(db, integration_id)
    secrets = decrypt_secrets(integ.secrets)
    secrets.pop("refresh_token", None)
    config = json.loads(integ.config or "{}")
    config.pop("upload_channel_title", None)
    config.pop("upload_channel_id", None)
    integ.config, integ.secrets = json.dumps(config), encrypt_secrets(secrets)
    db.commit()
    db.refresh(integ)
    return serialize(integ)


# ---------------------------------------------------------------- Rumble "Send to CRM" bookmark import
class RumbleImportIn(BaseModel):
    videos: list[dict] = Field(default_factory=list, max_length=5000)
    followers: int | None = None
    channel_url: str = Field(default="", max_length=500)


@router.post("/rumble/import")
def rumble_import(data: RumbleImportIn, integration_id: int | None = None, db: Session = Depends(get_db)):
    """Views/likes/comments read by the bookmark in your own browser (works even when Rumble blocks the server)."""
    from ..integrations import rumble
    from ..integrations.service import _context, update_total_views
    from ..models import utcnow
    q = select(Integration).where(Integration.provider == "rumble")
    rumbles = db.scalars(q).all()
    integ = next((i for i in rumbles if i.id == integration_id), None) if integration_id else None
    if integ is None and data.channel_url:
        want = rumble.channel_base(data.channel_url).lower()
        integ = next((i for i in rumbles if rumble.channel_base(json.loads(i.config or "{}").get("channel_url", "")).lower() == want), None)
    if integ is None and len(rumbles) == 1:
        integ = rumbles[0]
    if integ is None:
        raise HTTPException(422, "Add a Rumble connection on the Integrations page first (or one for this channel).")
    videos = [v for v in (rumble.normalize_video(x) for x in data.videos if isinstance(x, dict)) if v]
    if not videos:
        raise HTTPException(422, "No videos were found on that page. Open your channel's Videos tab on rumble.com and click the bookmark again.")
    ctx = _context(db, integ, None)
    n = rumble.save_videos(ctx, videos)
    if data.followers is not None and data.followers >= 0:
        ctx.channel.followers = data.followers
        ctx.stats["followers"] = data.followers
    if data.channel_url and not ctx.channel.url:
        ctx.channel.url = rumble.channel_base(data.channel_url)
    db.flush()
    update_total_views(db, ctx)
    integ.last_status, integ.last_error, integ.last_sync_at = "ok", "", utcnow()
    integ.last_result = json.dumps({**ctx.stats, "warnings": ["Imported from your browser with the Send to CRM bookmark."]})
    db.commit()
    return {"imported": n, "total_views": ctx.channel.total_views, "integration": serialize(integ)}

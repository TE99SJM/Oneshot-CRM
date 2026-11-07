"""Public (no login) sign-in return pages.

``GET /api/oauth/youtube/callback?code=…&state=…`` — Google sends your browser here after "Open Google sign-in"
when the YouTube connection uses the automatic return address. Only this ``/api/oauth`` path needs to be public
(for example ``sudo tailscale funnel --bg --set-path=/api/oauth http://127.0.0.1:3050/api/oauth``). The random
one-time ``state`` ties the visit to the sign-in you started, so nobody else can use it.

Like the eBay routes, a doubled ``/api/oauth`` prefix from a proxy is accepted.
"""
import html
import hmac
import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from ..database import SessionLocal
from ..integrations.base import SyncError
from ..integrations.crypto import decrypt_secrets
from ..models import Integration

log = logging.getLogger("oauth")
router = APIRouter(tags=["oauth-public"])


def _page(title: str, msg: str, ok: bool, link: str = "") -> HTMLResponse:
    color = "#0f766e" if ok else "#b91c1c"
    a = f'<p><a href="{html.escape(link)}">Back to the CRM</a></p>' if link else ""
    return HTMLResponse(f"""<!doctype html><meta name=viewport content="width=device-width"><title>{html.escape(title)}</title>
<body style="font-family:system-ui;max-width:560px;margin:60px auto;padding:0 20px;line-height:1.5">
<h2 style="color:{color}">{html.escape(title)}</h2><p>{html.escape(msg)}</p>{a}</body>""", status_code=200 if ok else 400)


def _back(return_to: str, **params) -> RedirectResponse:
    return RedirectResponse(f"{return_to}/integrations?{urlencode(params)}", status_code=303)


def _app_callback(mod, request: Request):
    """Return from TikTok / TikTok Shop sign-in."""
    from .oauth_apps import finish_signin
    q = request.query_params
    state, key = q.get("state", ""), mod.INFO.key
    flag = f"{key}_signin"
    with SessionLocal() as db:
        candidates, integ = [], None
        for i in db.scalars(select(Integration).where(Integration.provider == key)).all():
            try:
                s = decrypt_secrets(i.secrets)
            except ValueError:
                continue
            if s.get("oauth_state"):
                candidates.append(i)
                if state and hmac.compare_digest(s["oauth_state"], state):
                    integ = i
                    break
        if integ is None and not state and len(candidates) == 1:
            integ = candidates[0]              # TikTok Shop links made in Partner Center may drop the state
        if integ is None:
            return _page("Sign-in link expired",
                         f"This sign-in wasn't started from the CRM, or it was already used. In the CRM, open "
                         f"Integrations → {mod.OAUTH_NAME} → Sign in and try again.", False)
        return_to = json.loads(integ.config or "{}").get("oauth_return_to", "")
        if q.get("error"):
            msg = q.get("error_description") or q.get("error")
            msg = f"{mod.OAUTH_NAME} sign-in was cancelled." if q.get("error") == "access_denied" else f"{mod.OAUTH_NAME} said: {msg}"
            return _back(return_to, **{flag: "error", "message": msg}) if return_to else _page("Not connected", msg, False)
        try:
            finish_signin(db, integ, q.get("code") or q.get("auth_code") or "")
        except SyncError as e:
            log.warning("%s sign-in failed: %s", key, e)
            return _back(return_to, **{flag: "error", "message": str(e)}) if return_to else _page("Not connected", str(e), False)
        account = json.loads(integ.config or "{}").get("oauth_account", "")
        if return_to:
            return _back(return_to, **{flag: "connected", "account": account})
        return _page(f"{mod.OAUTH_NAME} connected", f"Signed in{f' as {account}' if account else ''}. You can close this tab.", True)


@router.get("/api/oauth/{rest:path}", include_in_schema=False)
def oauth_public(rest: str, request: Request):
    from .integrations import finish_youtube_signin
    from ..integrations.registry import OAUTH_APPS
    path = rest.rstrip("/")
    for mod in OAUTH_APPS.values():
        if path.endswith(f"{mod.OAUTH_SLUG}/callback"):
            return _app_callback(mod, request)
    if not path.endswith("youtube/callback"):
        return _page("Not found", "Unknown sign-in address.", False)
    q = request.query_params
    state = q.get("state", "")
    with SessionLocal() as db:
        integ, secrets = None, {}
        for i in db.scalars(select(Integration).where(Integration.provider == "youtube")).all():
            try:
                s = decrypt_secrets(i.secrets)
            except ValueError:
                continue
            if state and s.get("oauth_state") and hmac.compare_digest(s["oauth_state"], state):
                integ, secrets = i, s
                break
        if integ is None:
            return _page("Sign-in link expired",
                         "This sign-in wasn't started from the CRM, or it was already used. In the CRM, open "
                         "Integrations → YouTube → Set up posting and click “Open Google sign-in” again.", False)
        return_to = secrets.get("oauth_return_to", "")
        if q.get("error"):
            msg = "The Google sign-in was cancelled." if q.get("error") == "access_denied" else f"Google said: {q.get('error')}"
            return _back(return_to, youtube_posting="error", message=msg) if return_to else _page("Not connected", msg, False)
        try:
            finish_youtube_signin(db, integ, q.get("code", ""))
        except SyncError as e:
            log.warning("youtube sign-in failed: %s", e)
            return _back(return_to, youtube_posting="error", message=str(e)) if return_to else _page("Not connected", str(e), False)
        title = json.loads(integ.config or "{}").get("upload_channel_title", "")
        if return_to:
            return _back(return_to, youtube_posting="connected", channel=title)
        return _page("YouTube posting is on", f"Signed in{f' as {title}' if title else ''}. You can close this tab.", True)

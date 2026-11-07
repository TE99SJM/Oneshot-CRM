"""Shared sign-in plumbing for apps that send you back to the CRM with ``?code=…&state=…``
(TikTok, TikTok Shop, TikTok business messages).

Each provider module offers:
  * ``OAUTH_SLUG``            -> public return address ``/api/oauth/<slug>/callback``
  * ``authorize_url(config, secrets, redirect_uri, state)``
  * ``exchange(client, config, secrets, code, redirect_uri) -> dict`` with keys
        ``secrets`` (tokens to save), ``config`` (non-secret details) and ``account`` (a display name)
  * ``OAUTH_NAME``            -> "TikTok", used in messages

Tokens that a platform rotates on refresh are saved straight away with ``save_tokens`` so a later error in
the same sync can't lose them.
"""
import json
import secrets as _secrets
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from ..models import Integration
from .base import SyncContext, SyncError
from .crypto import decrypt_secrets, encrypt_secrets

PUBLIC_KEYS = ("oauth_redirect", "oauth_redirect_uri", "public_base_url", "deletion_endpoint")


def callback_path(slug: str) -> str:
    return f"/api/oauth/{slug}/callback"


def known_public_base(db) -> str:
    """An https host the user already made public (Tailscale Funnel), from any saved connection."""
    for integ in db.scalars(select(Integration).order_by(Integration.id)).all():
        cfg = json.loads(integ.config or "{}")
        for k in PUBLIC_KEYS:
            v = str(cfg.get(k) or "").strip()
            if v.startswith("https://"):
                u = urlparse(v)
                if u.hostname and u.hostname not in ("localhost", "127.0.0.1"):
                    return f"https://{u.netloc}"
    return ""


def normalize_redirect(value: str, slug: str) -> str:
    """Accept a full address or just the host; must be https (TikTok rejects http and IP addresses)."""
    v = (value or "").strip()
    if not v:
        return ""
    if "://" not in v:
        v = f"https://{v}"
    u = urlparse(v)
    if u.scheme != "https" or not u.hostname:
        raise ValueError("The return address must start with https:// (TikTok doesn't accept http or IP addresses). "
                         "Use your Tailscale Funnel address, for example https://mserver.tailXXXX.ts.net")
    if u.hostname.replace(".", "").isdigit():
        raise ValueError("TikTok doesn't accept IP addresses. Use your Tailscale Funnel (…ts.net) address.")
    path = u.path.rstrip("/")
    if not path or path == "/":
        path = callback_path(slug)
    return f"https://{u.netloc}{path}"


def redirect_for(db, integ: Integration, slug: str) -> dict:
    cfg = json.loads(integ.config or "{}")
    base = known_public_base(db)
    suggested = f"{base}{callback_path(slug)}" if base else ""
    return {"saved": cfg.get("oauth_redirect") or "", "suggested": suggested, "callback_path": callback_path(slug)}


def extract_code(pasted: str) -> tuple[str, str]:
    """(code, state) from a pasted return address, a query string, or a bare code."""
    v = (pasted or "").strip()
    if not v:
        return "", ""
    if "code=" in v or "auth_code=" in v:
        q = parse_qs(urlparse(v).query if "?" in v else v.lstrip("?#"))
        code = (q.get("code") or q.get("auth_code") or [""])[0]
        return code.strip(), (q.get("state") or [""])[0]
    return v, ""


def new_state() -> str:
    return _secrets.token_urlsafe(24)


def save_tokens(ctx: SyncContext, **updates) -> None:
    """Persist refreshed tokens immediately (commits the current session)."""
    ctx.secrets.update({k: v for k, v in updates.items() if v is not None})
    if ctx.integration_id is None:
        return
    integ = ctx.db.get(Integration, ctx.integration_id)
    if integ is None:
        return
    stored = decrypt_secrets(integ.secrets)
    stored.update({k: str(v) for k, v in updates.items() if v is not None})
    integ.secrets = encrypt_secrets(stored)
    ctx.db.commit()


def require_signed_in(ctx: SyncContext, name: str) -> None:
    if not ctx.secrets.get("refresh_token") and not ctx.secrets.get("access_token"):
        raise SyncError(f"{name}: not signed in yet. On the Integrations page click “Sign in” on this connection.")

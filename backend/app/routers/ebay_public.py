"""Public (no login) eBay endpoints.  Only these paths need to be reachable from the internet.

* ``GET  /api/ebay/account-deletion?challenge_code=…``  eBay's endpoint validation
* ``POST /api/ebay/account-deletion``                   a buyer closed their eBay account: delete their data
* ``GET  /api/ebay/oauth/callback?code=…&state=…``       optional automatic finish of "Sign in with eBay"

The catch-all path also accepts these with an extra ``/api/ebay`` prefix, so a reverse proxy
(e.g. Tailscale Funnel ``--set-path``) works whether or not it strips the mount path.
"""
import html
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import select

from ..database import SessionLocal
from ..integrations import base, ebay
from ..integrations.crypto import decrypt_secrets, encrypt_secrets
from ..models import Integration

log = logging.getLogger("ebay")
router = APIRouter(tags=["ebay-public"])


def _ebay_integrations(db) -> list[Integration]:
    return list(db.scalars(select(Integration).where(Integration.provider == "ebay").order_by(Integration.id)))


def _process_deletion(body: bytes, signature: str) -> None:
    try:
        payload = json.loads(body or b"{}")
        data = (payload.get("notification") or {}).get("data") or {}
        username = data.get("username") or ""
    except ValueError:
        return
    with SessionLocal() as db:
        integs = _ebay_integrations(db)
        verdict = None
        if integs and signature:
            i = integs[0]
            try:
                with base.make_client() as client:
                    verdict = ebay.verify_notification(client, json.loads(i.config or "{}"),
                                                       decrypt_secrets(i.secrets), body, signature)
            except ValueError:
                verdict = None
        if verdict is False:
            log.warning("Ignored eBay deletion notice with an invalid signature (user %s)", username)
            return
        n = ebay.delete_buyer_data(db, username)
        log.info("eBay account deletion for %s: removed %d records", username, n)


def _page(title: str, msg: str, ok: bool) -> HTMLResponse:
    color = "#0f766e" if ok else "#b91c1c"
    return HTMLResponse(f"""<!doctype html><meta name=viewport content="width=device-width"><title>{html.escape(title)}</title>
<body style="font-family:system-ui;max-width:560px;margin:60px auto;padding:0 20px;line-height:1.5">
<h2 style="color:{color}">{html.escape(title)}</h2><p>{html.escape(msg)}</p></body>""", status_code=200 if ok else 400)


@router.api_route("/api/ebay/{rest:path}", methods=["GET", "POST"], include_in_schema=False)
async def ebay_public(rest: str, request: Request, background: BackgroundTasks):
    path = rest.rstrip("/")
    if path.endswith("account-deletion"):
        if request.method == "POST":
            body = await request.body()
            background.add_task(_process_deletion, body, request.headers.get("x-ebay-signature", ""))
            return Response(status_code=204)               # acknowledge immediately, as eBay requires
        code = request.query_params.get("challenge_code", "")
        with SessionLocal() as db:
            integ = next((i for i in _ebay_integrations(db) if json.loads(i.config or "{}").get("deletion_endpoint")), None)
            if integ is None:
                return JSONResponse({"detail": "No eBay connection has an account-deletion URL saved yet."}, status_code=404)
            cfg = json.loads(integ.config or "{}")
        if not code:
            return JSONResponse({"ok": True, "detail": "eBay account-deletion endpoint is reachable."})
        return JSONResponse({"challengeResponse": ebay.challenge_response(code, cfg.get("verification_token", ""),
                                                                          cfg["deletion_endpoint"].strip())})
    if path.endswith("oauth/callback") and request.method == "GET":
        if request.query_params.get("isAuthSuccessful") == "false" or not request.query_params.get("code"):
            return _page("eBay sign-in was not completed", "Go back to the CRM and click “Sign in with eBay” again.", False)
        iid = ebay.read_state(request.query_params.get("state", ""))
        with SessionLocal() as db:
            integ = db.get(Integration, iid) if iid else None
            if integ is None or integ.provider != "ebay":
                return _page("Unknown sign-in link", "Start again from the CRM's Integrations page.", False)
            try:
                finish_connect(db, integ, request.query_params["code"])
            except (base.SyncError, ValueError) as e:
                return _page("eBay sign-in failed", str(e), False)
        return _page("eBay connected", "You can close this tab. Back in the CRM, click Sync now on the eBay connection.", True)
    return JSONResponse({"detail": "Not found"}, status_code=404)


def finish_connect(db, integ: Integration, code: str) -> None:
    config = json.loads(integ.config or "{}")
    secrets = decrypt_secrets(integ.secrets)
    with base.make_client() as client:
        tok = ebay.exchange_code(client, config, secrets, code)
    secrets["refresh_token"] = tok["refresh_token"]
    integ.secrets = encrypt_secrets(secrets)
    from ..models import utcnow
    from datetime import timedelta
    exp = tok.get("refresh_token_expires_in")
    config["signed_in_at"] = utcnow().isoformat(timespec="seconds")
    if exp:
        config["refresh_expires_at"] = (utcnow() + timedelta(seconds=int(exp))).isoformat(timespec="seconds")
    integ.config = json.dumps(config)
    integ.last_status, integ.last_error = ("never" if integ.last_status == "error" else integ.last_status), ""
    db.commit()

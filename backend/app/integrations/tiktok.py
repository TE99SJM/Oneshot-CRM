"""TikTok account: followers, likes and every video's views/likes/comments/shares (Login Kit + Display API),
plus the sign-in that posting (Content Posting API) uses.

Docs: https://developers.tiktok.com/doc/login-kit-web , https://developers.tiktok.com/doc/tiktok-api-v2-get-user-info ,
https://developers.tiktok.com/doc/tiktok-api-v2-video-list , https://developers.tiktok.com/doc/content-posting-api-get-started
"""
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, upsert_post
from .oauth_apps import require_signed_in, save_tokens

OAUTH_SLUG = "tiktok"
OAUTH_NAME = "TikTok"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
TOKEN_URL = f"{API}/oauth/token/"
SCOPES = ["user.info.basic", "user.info.profile", "user.info.stats", "video.list", "video.publish", "video.upload"]
USER_FIELDS = "open_id,union_id,avatar_url,display_name,username,profile_deep_link,bio_description,is_verified," \
              "follower_count,following_count,likes_count,video_count"
VIDEO_FIELDS = "id,title,video_description,create_time,share_url,cover_image_url,duration,view_count,like_count," \
               "comment_count,share_count"

INFO = ProviderInfo(
    key="tiktok", name="TikTok", platform="tiktok", channel_kind="social",
    summary="Followers, total likes, and every video's views, likes, comments and shares. Also lets Compose post videos and photos.",
    syncs=["Followers, following, total likes", "Videos (views, likes, comments, shares)", "Posting from Compose"],
    fields=[
        FieldSpec("client_key", "Client key", placeholder="aw1b2c3d4e5f…",
                  help="From developers.tiktok.com → Manage apps → your app → App details."),
        FieldSpec("client_secret", "Client secret", secret=True),
        FieldSpec("max_videos", "Videos to sync", required=False, default="200",
                  help="How many of your newest videos to keep stats for (max 1000)."),
    ],
    docs_url="https://developers.tiktok.com/doc/login-kit-web",
    steps=[
        "Go to developers.tiktok.com, log in with your TikTok account, and click Manage apps → Connect an app.",
        "Add the products Login Kit and Content Posting API. Under Content Posting API turn on Direct Post.",
        "Add the scopes user.info.basic, user.info.profile, user.info.stats, video.list, video.publish and video.upload.",
        "Under Login Kit → Redirect URI add the return address shown after you click Sign in here "
        "(your Tailscale Funnel address ending in /api/oauth/tiktok/callback).",
        "Copy the Client key and Client secret into this form, save, then click “Sign in” on the TikTok card.",
        "Until TikTok approves your app (app review + Content Posting audit), it works for your own account (add it as a "
        "Sandbox/target user) and posts made through the API can only be private (“Only me”).",
    ],
)


# ---------------------------------------------------------------- sign-in
def authorize_url(config: dict, secrets: dict, redirect_uri: str, state: str) -> str:
    key = (config.get("client_key") or "").strip()
    if not key:
        raise SyncError("TikTok: enter the Client key first (Edit)")
    return f"{AUTH_URL}?" + urlencode({"client_key": key, "response_type": "code", "scope": ",".join(SCOPES),
                                      "redirect_uri": redirect_uri, "state": state})


def _token_call(client, config: dict, secrets: dict, data: dict) -> dict:
    if not (config.get("client_key") and secrets.get("client_secret")):
        raise SyncError("TikTok: Client key and Client secret are required")
    resp = client.post(TOKEN_URL, data={"client_key": config["client_key"].strip(),
                                        "client_secret": secrets["client_secret"].strip(), **data},
                       headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"})
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400 or body.get("error") or not body.get("access_token"):
        desc = body.get("error_description") or body.get("error") or resp.text[:200]
        hint = ""
        if "redirect" in str(desc).lower():
            hint = " Check that the Redirect URI in your TikTok app matches the return address in the CRM exactly."
        raise SyncError(f"TikTok sign-in failed: {desc}.{hint}")
    return body


def _token_fields(body: dict) -> dict:
    now = int(time.time())
    return {"access_token": body["access_token"], "refresh_token": body.get("refresh_token") or "",
            "token_expires": str(now + int(body.get("expires_in") or 86400) - 120),
            "open_id": body.get("open_id") or ""}


def exchange(client, config: dict, secrets: dict, code: str, redirect_uri: str) -> dict:
    body = _token_call(client, config, secrets, {"code": code, "grant_type": "authorization_code",
                                                 "redirect_uri": redirect_uri})
    tok = _token_fields(body)
    granted = set(str(body.get("scope") or "").split(","))
    account, username = "", ""
    try:
        user = _get(client, tok["access_token"], "/user/info/", fields="open_id,display_name,username")
        account = user.get("display_name") or user.get("username") or ""
        username = user.get("username") or ""
    except SyncError:
        pass
    missing = [s for s in SCOPES if granted and s not in granted]
    return {"secrets": tok, "account": account,
            "config": {"username": username, "granted_scopes": ",".join(sorted(granted)), "missing_scopes": ",".join(missing)}}


def access_token(ctx: SyncContext) -> str:
    require_signed_in(ctx, "TikTok")
    s = ctx.secrets
    if s.get("access_token") and int(s.get("token_expires") or 0) > time.time():
        return s["access_token"]
    if not s.get("refresh_token"):
        raise SyncError("TikTok: sign-in expired. Click “Sign in” on the TikTok card again.")
    body = _token_call(ctx.client, ctx.config, s, {"grant_type": "refresh_token", "refresh_token": s["refresh_token"]})
    save_tokens(ctx, **_token_fields(body))
    return ctx.secrets["access_token"]


# ---------------------------------------------------------------- API helpers
def _check(resp, what: str = "TikTok") -> dict:
    try:
        body = resp.json()
    except ValueError:
        raise SyncError(f"{what}: HTTP {resp.status_code} {resp.text[:200]}") from None
    err = body.get("error") or {}
    code = err.get("code") if isinstance(err, dict) else err
    if resp.status_code >= 400 or (code and code != "ok"):
        msg = (err.get("message") if isinstance(err, dict) else "") or str(code) or f"HTTP {resp.status_code}"
        hint = {
            "scope_not_authorized": " Turn on the missing scope in your TikTok app, then click Sign in again.",
            "access_token_invalid": " Click Sign in on the TikTok card again.",
            "unaudited_client_can_only_post_to_private_accounts":
                " Until TikTok audits your app, set your TikTok account to Private and post as “Only me”.",
            "spam_risk_too_many_posts": " TikTok's daily posting limit was reached; try again tomorrow.",
            "privacy_level_option_mismatch": " Pick one of the visibility options TikTok offered for your account.",
        }.get(str(code), "")
        raise SyncError(f"{what}: {msg} ({code}).{hint}" if code else f"{what}: {msg}")
    return body.get("data") or {}


def _get(client, token: str, path: str, **params) -> dict:
    data = _check(client.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {token}"}))
    return data.get("user", data) if path.startswith("/user/") else data


def api_post(client, token: str, path: str, body: dict, params: dict | None = None, what: str = "TikTok") -> dict:
    return _check(client.post(f"{API}{path}", params=params or {}, json=body,
                              headers={"Authorization": f"Bearer {token}",
                                       "Content-Type": "application/json; charset=UTF-8"}), what)


def test(ctx: SyncContext) -> str:
    token = access_token(ctx)
    u = _get(ctx.client, token, "/user/info/", fields="open_id,display_name,username")
    return f"Connected to TikTok as {u.get('display_name') or u.get('username') or 'your account'}"


def sync(ctx: SyncContext) -> None:
    token = access_token(ctx)
    try:
        u = _get(ctx.client, token, "/user/info/", fields=USER_FIELDS)
    except SyncError as e:
        if "scope" not in str(e).lower():
            raise
        ctx.warnings.append(f"Some profile stats aren't allowed yet ({e}).")
        u = _get(ctx.client, token, "/user/info/", fields="open_id,avatar_url,display_name")
    name = u.get("display_name") or u.get("username") or "TikTok"
    ch = ctx.channel
    if u.get("follower_count") is not None:
        ch.followers = int(u["follower_count"])
        ctx.stats["followers"] = ch.followers
    if u.get("profile_deep_link") and not ch.url:
        ch.url = u["profile_deep_link"]
    if u.get("username"):
        ch.handle = ch.handle or f"@{u['username']}"
    for k in ("following_count", "likes_count", "video_count"):
        if u.get(k) is not None:
            ctx.stats[k.replace("_count", "")] = int(u[k])
    ctx.metric("followers", u.get("follower_count"), "Followers")
    ctx.metric("following", u.get("following_count"))
    ctx.metric("total_likes_received", u.get("likes_count"), "Total likes received")
    ctx.metric("video_count", u.get("video_count"), "Public videos")
    ctx.stats["account"] = name

    try:
        limit = max(1, min(int(ctx.config.get("max_videos") or 200), 1000))
    except ValueError:
        limit = 200
    cursor, seen = None, 0
    while seen < limit:
        body = {"max_count": 20, **({"cursor": cursor} if cursor else {})}
        try:
            data = api_post(ctx.client, token, "/video/list/", body, params={"fields": VIDEO_FIELDS})
        except SyncError as e:
            ctx.warnings.append(f"Videos unavailable ({e}).")
            break
        videos = data.get("videos") or []
        for v in videos:
            seen += 1
            created = datetime.fromtimestamp(int(v["create_time"]), tz=timezone.utc).replace(tzinfo=None) \
                if v.get("create_time") else None
            title = v.get("title") or (v.get("video_description") or "").split("\n")[0] or "TikTok video"
            upsert_post(ctx, "tiktok", str(v["id"]), title=title[:200], body=v.get("video_description") or "",
                        url=v.get("share_url") or "", published_at=created, views=int(v.get("view_count") or 0),
                        likes=int(v.get("like_count") or 0), comments=int(v.get("comment_count") or 0),
                        shares=int(v.get("share_count") or 0))
        if not data.get("has_more") or not videos:
            break
        cursor = data.get("cursor")
    ctx.stats["videos_read"] = seen

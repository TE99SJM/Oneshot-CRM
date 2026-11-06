"""Twitch Helix API with an app access token (client credentials): followers, live status, VOD views."""
from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, parse_dt, upsert_post

HELIX = "https://api.twitch.tv/helix"

INFO = ProviderInfo(
    key="twitch", name="Twitch", platform="twitch", channel_kind="social",
    summary="Follower total, whether you're live (and viewer count), and your past broadcasts/clips with views.",
    syncs=["Followers", "Live now + viewers", "Videos (views)"],
    fields=[
        FieldSpec("login", "Channel name", placeholder="theforge_sports",
                  help="The name in your channel URL: twitch.tv/<this part>."),
        FieldSpec("client_id", "Client ID", placeholder="abc123...", help="From your app at dev.twitch.tv/console."),
        FieldSpec("client_secret", "Client secret", secret=True, placeholder="xyz789...",
                  help="Click New Secret on the same app page."),
        FieldSpec("max_videos", "Videos to sync", required=False, default="100", placeholder="100"),
    ],
    steps=[
        "Go to dev.twitch.tv/console and log in with your Twitch account (turn on two-factor authentication if it asks).",
        "Click Register Your Application. Name: anything (e.g. Oneshot CRM). OAuth Redirect URL: http://localhost. Category: Analytics Tool. Client type: Confidential.",
        "Open the app (Manage), copy the Client ID, then click New Secret and copy the Client Secret.",
        "Paste your channel name, Client ID and Client Secret here.",
    ],
    docs_url="https://dev.twitch.tv/docs/api/get-started/",
)


def _token(ctx) -> str:
    cid, secret = (ctx.config.get("client_id") or "").strip(), (ctx.secrets.get("client_secret") or "").strip()
    if not cid or not secret:
        raise SyncError("Twitch: enter the Client ID and Client Secret")
    data = check_response(ctx.client.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": cid, "client_secret": secret, "grant_type": "client_credentials"}), "Twitch")
    return data["access_token"]


def _helix(ctx, token, path, **params):
    headers = {"Authorization": f"Bearer {token}", "Client-Id": ctx.config.get("client_id", "").strip()}
    return check_response(ctx.client.get(f"{HELIX}/{path}", headers=headers, params=params), "Twitch")


def _login(ctx) -> str:
    v = (ctx.config.get("login") or "").strip().rstrip("/")
    if "twitch.tv/" in v:
        v = v.split("twitch.tv/")[1].split("/")[0]
    v = v.lstrip("@").lower()
    if not v:
        raise SyncError("Twitch: enter your channel name")
    return v


def _user(ctx, token) -> dict:
    users = _helix(ctx, token, "users", login=_login(ctx)).get("data", [])
    if not users:
        raise SyncError(f"Twitch: no channel named '{_login(ctx)}'")
    return users[0]


def _followers(ctx, token, uid) -> int | None:
    try:
        return int(_helix(ctx, token, "channels/followers", broadcaster_id=uid).get("total", 0))
    except SyncError as e:
        ctx.warnings.append(f"Follower total unavailable ({e}).")
        return None


def test(ctx: SyncContext) -> str:
    token = _token(ctx)
    u = _user(ctx, token)
    f = _followers(ctx, token, u["id"])
    return f"Connected to {u.get('display_name', u['login'])}" + (f" ({f} followers)" if f is not None else "")


def sync(ctx: SyncContext) -> None:
    token = _token(ctx)
    u = _user(ctx, token)
    ctx.channel.handle = ctx.channel.handle or u["login"]
    ctx.channel.url = ctx.channel.url or f"https://www.twitch.tv/{u['login']}"
    f = _followers(ctx, token, u["id"])
    if f is not None:
        ctx.channel.followers = f
        ctx.stats["followers"] = f
    live = _helix(ctx, token, "streams", user_id=u["id"]).get("data", [])
    ctx.stats["live_now"] = 1 if live else 0
    if live:
        ctx.stats["live_viewers"] = int(live[0].get("viewer_count", 0))
    limit = max(1, min(int(ctx.config.get("max_videos") or 100), 500))
    videos, cursor = [], None
    while len(videos) < limit:
        data = _helix(ctx, token, "videos", user_id=u["id"], first=100, **({"after": cursor} if cursor else {}))
        videos += data.get("data", [])
        cursor = data.get("pagination", {}).get("cursor")
        if not cursor:
            break
    for v in videos[:limit]:
        upsert_post(ctx, "twitch", v["id"], title=v.get("title") or "Twitch video", body=v.get("description", ""),
                    url=v.get("url", ""), published_at=parse_dt(v.get("published_at") or v.get("created_at")),
                    views=int(v.get("view_count", 0)))

"""Twitch Helix API with an app access token (client credentials): followers, live status, VOD views."""
from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, parse_dt, upsert_post

HELIX = "https://api.twitch.tv/helix"

INFO = ProviderInfo(
    key="twitch", name="Twitch", platform="twitch", channel_kind="social",
    summary="Follower total, whether you're live (and viewer count), and your past broadcasts, highlights and clips with views.",
    syncs=["Followers", "Live now + viewers", "Videos (views)", "Clips (views)"],
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


def _dur(v: str | None) -> int:
    """Twitch durations look like 3h21m5s."""
    import re
    total = 0
    for n, u in re.findall(r"(\d+)([hms])", v or ""):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[u]
    return total


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
    ctx.metric("followers", f, "Followers")
    ctx.metric("live_now", 1 if live else 0, window="live")
    ctx.metric("live_viewers", int(live[0].get("viewer_count", 0)) if live else 0, window="live")
    if live and parse_dt(live[0].get("started_at")):
        from ..models import utcnow
        ctx.metric("live_minutes", round((utcnow() - parse_dt(live[0]["started_at"])).total_seconds() / 60),
                   "Minutes live (current stream)", "minutes", "Live", "live")
    ctx.metric("twitch_lifetime_views", u.get("view_count") or None, "Channel views (Twitch's old counter)", "num", "Views")
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
    # Clips made from your channel (by you or viewers) have their own view counts.
    clips, cursor, pages = [], None, 0
    while len(clips) < limit and pages < 10:
        try:
            data = _helix(ctx, token, "clips", broadcaster_id=u["id"], first=100, **({"after": cursor} if cursor else {}))
        except SyncError as e:
            ctx.warnings.append(f"Clips unavailable ({e}).")
            break
        clips += data.get("data", [])
        cursor = (data.get("pagination") or {}).get("cursor")
        pages += 1
        if not cursor:
            break
    for c in clips[:limit]:
        upsert_post(ctx, "twitch", f"clip:{c['id']}", title=f"Clip: {c.get('title') or 'Twitch clip'}",
                    url=c.get("url", ""), published_at=parse_dt(c.get("created_at")), views=int(c.get("view_count", 0)))
    vids = videos[:limit]
    ctx.metric("twitch_videos", len(vids), "Past broadcasts / highlights / uploads", "num", "Content")
    ctx.metric("twitch_video_views", sum(int(v.get("view_count", 0)) for v in vids), "Views on videos", "num", "Views")
    ctx.metric("twitch_broadcast_hours", round(sum(_dur(v.get("duration")) for v in vids) / 3600, 1),
               "Hours of saved video", "hours", "Content")
    ctx.metric("twitch_clips", len(clips[:limit]), "Clips", "num", "Content")
    ctx.metric("twitch_clip_views", sum(int(c.get("view_count", 0)) for c in clips[:limit]), "Views on clips", "num", "Views")
    if not videos and not clips:
        ctx.warnings.append("No past broadcasts or clips found. Twitch deletes past broadcasts after 7-60 days unless you "
                            "turn on “Store past broadcasts” (Creator Dashboard → Settings → Stream) or save them as highlights.")

"""YouTube Data API v3 (API key): subscriber count + recent uploads with views/likes/comments."""
from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, parse_dt, upsert_post

API = "https://www.googleapis.com/youtube/v3"

INFO = ProviderInfo(
    key="youtube", name="YouTube", platform="youtube", channel_kind="social",
    summary="Subscriber count and your recent videos with views, likes and comments.",
    syncs=["Channel subscribers", "Recent uploads (views, likes, comments)"],
    fields=[
        FieldSpec("channel", "Channel handle or ID", placeholder="@yourhandle or UCxxxxxxxx",
                  help="Your @handle from your channel URL, or the channel ID that starts with UC."),
        FieldSpec("api_key", "API key", secret=True, placeholder="AIza...",
                  help="A Google Cloud API key with YouTube Data API v3 enabled."),
        FieldSpec("max_videos", "Videos to sync", required=False, default="100", placeholder="100",
                  help="How many of your most recent uploads to track (max 500)."),
    ],
    steps=[
        "Go to console.cloud.google.com and sign in with the Google account that owns the channel.",
        "Create a project (top bar → project picker → New project). Any name works.",
        "Open APIs & Services → Library, search for “YouTube Data API v3” and click Enable.",
        "Open APIs & Services → Credentials → Create credentials → API key. Copy the key.",
        "Recommended: click the key → API restrictions → Restrict key → choose YouTube Data API v3 → Save.",
        "Paste the key here along with your channel handle (for example @gamingoutdoorsmen).",
    ],
    docs_url="https://developers.google.com/youtube/v3/getting-started",
)


def _get(ctx: SyncContext, path: str, **params):
    params["key"] = ctx.secrets.get("api_key", "")
    return check_response(ctx.client.get(f"{API}/{path}", params=params), "YouTube")


def _channel(ctx: SyncContext) -> dict:
    ident = (ctx.config.get("channel") or "").strip()
    if not ident:
        raise SyncError("YouTube: enter a channel handle or ID")
    for prefix in ("https://www.youtube.com/", "https://youtube.com/", "youtube.com/"):
        if ident.startswith(prefix):
            ident = ident[len(prefix):].split("/")[0] if not ident[len(prefix):].startswith("channel/") \
                else ident[len(prefix) + 8:].split("/")[0]
    params = {"part": "snippet,statistics,contentDetails"}
    if ident.startswith("UC") and len(ident) == 24:
        params["id"] = ident
    else:
        params["forHandle"] = ident if ident.startswith("@") else f"@{ident}"
    data = _get(ctx, "channels", **params)
    items = data.get("items") or []
    if not items:
        raise SyncError(f"YouTube: no channel found for '{ident}'")
    return items[0]


def test(ctx: SyncContext) -> str:
    ch = _channel(ctx)
    subs = ch.get("statistics", {}).get("subscriberCount", "hidden")
    return f"Connected to {ch['snippet']['title']} ({subs} subscribers)"


def sync(ctx: SyncContext) -> None:
    ch = _channel(ctx)
    stats = ch.get("statistics", {})
    if not stats.get("hiddenSubscriberCount"):
        ctx.channel.followers = int(stats.get("subscriberCount", 0))
    ctx.channel.handle = ctx.channel.handle or ch["snippet"].get("customUrl", "")
    ctx.channel.url = ctx.channel.url or f"https://www.youtube.com/channel/{ch['id']}"
    ctx.stats["followers"] = ctx.channel.followers
    ctx.stats["total_channel_views"] = int(stats.get("viewCount", 0))

    uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        return
    limit = max(1, min(int(ctx.config.get("max_videos") or 100), 500))
    video_ids: list[str] = []
    page = None
    while len(video_ids) < limit:
        data = _get(ctx, "playlistItems", part="contentDetails", playlistId=uploads, maxResults=50,
                    **({"pageToken": page} if page else {}))
        video_ids += [i["contentDetails"]["videoId"] for i in data.get("items", [])]
        page = data.get("nextPageToken")
        if not page:
            break
    video_ids = video_ids[:limit]

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]
        data = _get(ctx, "videos", part="snippet,statistics", id=",".join(batch), maxResults=50)
        for v in data.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            upsert_post(ctx, "youtube", v["id"], title=sn.get("title", ""), body=sn.get("description", "")[:5000],
                        url=f"https://www.youtube.com/watch?v={v['id']}", published_at=parse_dt(sn.get("publishedAt")),
                        views=int(st.get("viewCount", 0)), likes=int(st.get("likeCount", 0)),
                        comments=int(st.get("commentCount", 0)))

"""Rumble: no public video-stats API exists, so we combine sources.

1. The official Live Stream API URL (rumble.com/account/livestream-api) gives followers,
   subscribers and live streams.
2. Your public channel videos pages (rumble.com/c/NAME/videos?page=N) carry each video's view
   count, likes and comments in a JSON block; we read those for per-video views.
3. If Rumble's anti-bot check blocks the server, the "Send to CRM" bookmark reads the same pages in
   your own browser and imports them (see import_videos()).
"""
import json
import re
from urllib.parse import urlparse

from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, parse_dt, upsert_post

INFO = ProviderInfo(
    key="rumble", name="Rumble", platform="rumble", channel_kind="social",
    summary="Followers, subscribers, live streams, and views/likes/comments for each of your videos (read from your public channel page).",
    syncs=["Followers", "Subscribers (Live Stream API)", "Live streams (Live Stream API)",
           "Video views, likes, comments (channel page)"],
    fields=[
        FieldSpec("api_url", "Live Stream API URL", secret=True, required=False,
                  placeholder="https://rumble.com/-livestream-api/get-data?key=...",
                  help="Optional but recommended. Copy the full URL from rumble.com/account/livestream-api."),
        FieldSpec("channel_url", "Channel page URL", required=False, placeholder="https://rumble.com/c/YourChannel",
                  help="Needed for video views. Your public channel page; also a backup for the follower count."),
        FieldSpec("max_pages", "Video pages to read", required=False, default="10",
                  help="Each page is about 25 videos. 10 pages = your newest ~250 videos."),
    ],
    steps=[
        "Sign in at rumble.com and open rumble.com/account/livestream-api (Profile menu → Live Stream API).",
        "If no key is shown, click to generate one. Copy the whole URL, which starts with https://rumble.com/-livestream-api/get-data?key=",
        "Paste it in the Live Stream API URL box. Treat it like a password because anyone with it can read your stream data.",
        "Add your channel page URL (for example https://rumble.com/c/YourChannel). The CRM reads each video's views, likes and comments from it.",
        "If a sync says Rumble blocked the request, use the “Send to CRM” bookmark on the Rumble card instead: open your channel's videos page in your browser and click the bookmark.",
    ],
    docs_url="https://rumble.support/help/how-to-use-rumble-s-live-stream-api",
)

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0 Safari/537.36")
FOLLOWERS_RE = re.compile(r"([\d][\d.,]*\s*[KkMmBb]?)\s*Followers", re.I)


def parse_count(text: str) -> int:
    t = text.strip().replace(",", "").replace(" ", "")
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(t[-1:].lower(), 1)
    if mult > 1:
        t = t[:-1]
    return int(round(float(t) * mult))


def _api(ctx: SyncContext) -> dict | None:
    url = (ctx.secrets.get("api_url") or "").strip()
    if not url:
        return None
    if not url.startswith("https://rumble.com/"):
        raise SyncError("Rumble: the Live Stream API URL must start with https://rumble.com/")
    return check_response(ctx.client.get(url), "Rumble")


def _page_followers(ctx: SyncContext) -> int | None:
    url = (ctx.config.get("channel_url") or "").strip()
    if not url:
        return None
    if not url.startswith("http"):
        url = f"https://rumble.com/c/{url.lstrip('/')}"
    resp = ctx.client.get(url, headers={"Accept": "text/html", "User-Agent": BROWSER_UA})
    if resp.status_code == 403:
        ctx.warnings.append("Rumble blocked the channel page request (anti-bot check). Use the “Send to CRM” bookmark on this card to import your video views from your browser, and add the Live Stream API URL for followers.")
        return None
    if resp.status_code >= 400:
        ctx.warnings.append(f"Rumble channel page returned HTTP {resp.status_code}.")
        return None
    m = FOLLOWERS_RE.search(resp.text)
    if not m:
        ctx.warnings.append("Couldn't find the follower count on the Rumble channel page.")
        return None
    return parse_count(m.group(1))


GRID_RE = re.compile(r'<rum-videos-grid[^>]*>\s*<script type="application/json">(.*?)</script>', re.S)
BLOCKED_MARKERS = ("Just a moment...", "challenges.cloudflare.com", "cf-chl")


def channel_base(url: str) -> str:
    """https://rumble.com/c/Name[/videos][?page=2] -> https://rumble.com/c/Name  (also /user/Name)."""
    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith("http"):
        u = f"https://{u}" if u.lower().startswith(("rumble.com", "www.rumble.com")) else f"https://rumble.com/c/{u.lstrip('/')}"
    p = urlparse(u)
    parts = [x for x in p.path.split("/") if x]
    if len(parts) >= 2 and parts[0] in ("c", "user"):
        return f"https://rumble.com/{parts[0]}/{parts[1]}"
    return f"https://rumble.com/{'/'.join(parts)}" if parts else ""


def parse_videos_page(html: str) -> tuple[list[dict], int | None]:
    """Video items + channel follower count from one channel videos page."""
    items, followers = [], None
    for block in GRID_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for it in data.get("items") or []:
            if not isinstance(it, dict) or it.get("object_type", "video") != "video":
                continue
            v = normalize_video(it)
            if v:
                items.append(v)
            by = it.get("by") or {}
            if followers is None and isinstance(by, dict) and isinstance(by.get("followers"), int):
                followers = by["followers"]
    return items, followers


def normalize_video(it: dict) -> dict | None:
    """Rumble item (page JSON or bookmark import) -> {key,title,url,published,views,likes,comments,live}."""
    key = it.get("permalink_id") or it.get("key") or it.get("eid") or it.get("id")
    url = it.get("url") or ""
    if not key and url:
        m = re.search(r"rumble\.com/(v[0-9a-z]+)-", url)
        key = m.group(1) if m else ""
    if not key:
        return None
    stats = it.get("video_stats") if isinstance(it.get("video_stats"), dict) else {}
    votes = it.get("rumble_votes") if isinstance(it.get("rumble_votes"), dict) else {}
    comments = it.get("comments")
    views = it.get("views")
    if not isinstance(views, (int, float)):
        views = stats.get("rumble_plays") or 0
    likes = it.get("likes") if isinstance(it.get("likes"), (int, float)) else votes.get("num_votes_up") or 0
    return {
        "key": str(key), "title": str(it.get("title") or "Rumble video")[:200],
        "url": url if url.startswith("http") else (f"https://rumble.com{url}" if url.startswith("/") else ""),
        "published": it.get("upload_date") or it.get("published") or it.get("live_streamed_on"),
        "views": int(views or 0), "likes": int(likes or 0),
        "comments": int(comments.get("count") or 0) if isinstance(comments, dict) else int(comments or 0),
    }


def save_videos(ctx: SyncContext, videos: list[dict]) -> int:
    seen = set()
    for v in videos:
        if v["key"] in seen:
            continue
        seen.add(v["key"])
        upsert_post(ctx, "rumble", v["key"], title=v["title"], url=v["url"], published_at=parse_dt(v["published"]),
                    views=v["views"], likes=v["likes"], comments=v["comments"])
    ctx.stats["videos_read"] = len(seen)
    return len(seen)


def _read_videos(ctx: SyncContext) -> tuple[list[dict], int | None]:
    """Read the channel's videos pages. Returns ([], None) with a warning if Rumble blocks us."""
    base = channel_base(ctx.config.get("channel_url") or "")
    if not base:
        ctx.warnings.append("Add your channel page URL (Edit) to read video views.")
        return [], None
    try:
        pages = max(1, min(int(ctx.config.get("max_pages") or 10), 100))
    except ValueError:
        pages = 10
    videos, followers = [], None
    for n in range(1, pages + 1):
        url = f"{base}/videos" + (f"?page={n}" if n > 1 else "")
        resp = ctx.client.get(url, headers={"Accept": "text/html", "User-Agent": BROWSER_UA})
        if resp.status_code == 404 and n > 1:
            break                                   # past the last page
        if resp.status_code in (403, 503) or any(m in resp.text[:6000] for m in BLOCKED_MARKERS):
            ctx.warnings.append("Rumble's anti-bot check blocked the server from reading your videos page. "
                                "Use the “Send to CRM” bookmark on the Rumble card to import views from your browser.")
            break
        if resp.status_code >= 400:
            ctx.warnings.append(f"Rumble videos page {n} returned HTTP {resp.status_code}.")
            break
        items, f = parse_videos_page(resp.text)
        followers = followers if followers is not None else f
        if not items:
            if n == 1:
                ctx.warnings.append("Couldn't find any videos on your Rumble videos page (Rumble may have changed its layout).")
            break
        videos += items
        if f'page={n + 1}' not in resp.text:
            break
    return videos, followers


def _api_counts(data: dict) -> tuple[int | None, int | None]:
    f = data.get("followers") or {}
    s = data.get("subscribers") or {}
    followers = f.get("num_followers_total", f.get("num_followers")) if isinstance(f, dict) else None
    subs = s.get("num_subscribers") if isinstance(s, dict) else None
    return (int(followers) if followers is not None else None, int(subs) if subs is not None else None)


def test(ctx: SyncContext) -> str:
    if not (ctx.secrets.get("api_url") or ctx.config.get("channel_url")):
        raise SyncError("Rumble: enter the Live Stream API URL or your channel page URL")
    data = _api(ctx)
    if data is not None:
        followers, subs = _api_counts(data)
        who = data.get("channel_name") or data.get("username") or "your account"
        return f"Connected to {who} via Live Stream API ({followers or 0} followers, {subs or 0} subscribers)"
    followers = _page_followers(ctx)
    if followers is None:
        raise SyncError("Rumble: " + (ctx.warnings[-1] if ctx.warnings else "couldn't read the channel page"))
    return f"Read channel page ({followers} followers)"


def sync(ctx: SyncContext) -> None:
    data = _api(ctx)
    followers = None
    if data is not None:
        followers, subs = _api_counts(data)
        if subs is not None:
            ctx.stats["subscribers"] = subs
        ctx.metric("subscribers", subs, "Subscribers (paid)")
        f_ = data.get("followers") or {}
        if isinstance(f_, dict):
            ctx.metric("rumble_followers_new", f_.get("num_followers"), "Followers (recent counter)", "num", "Audience")
        streams = [x for x in (data.get("livestreams") or []) if isinstance(x, dict)]
        ctx.metric("live_now", sum(1 for x in streams if x.get("is_live")), window="live")
        ctx.metric("live_viewers", sum(int(x.get("watching_now") or 0) for x in streams), window="live")
        ctx.metric("rumble_live_likes", sum(int(x.get("likes") or 0) for x in streams), "Likes on live streams", "num", "Live", "live")
        ctx.metric("rumble_live_dislikes", sum(int(x.get("dislikes") or 0) for x in streams), "Dislikes on live streams", "num", "Live", "live")
        rants = [r for x in streams for r in ((x.get("chat") or {}).get("recent_rants") or []) if isinstance(r, dict)]
        if rants:
            ctx.metric("rumble_rants", sum(float(r.get("amount_dollars") or 0) for r in rants), "Recent rants (tips)",
                       "money", "Revenue", "live")
        for ls in data.get("livestreams") or []:
            if not isinstance(ls, dict) or not ls.get("id"):
                continue
            chat = ls.get("chat") or {}
            upsert_post(ctx, "rumble", f"live:{ls['id']}", title=ls.get("title") or "Rumble live stream",
                        published_at=parse_dt(ls.get("created_on")),
                        views=int(ls.get("watching_now") or 0),
                        likes=int(ls.get("likes") or 0),
                        comments=len(chat.get("recent_messages") or []) if isinstance(chat, dict) else 0)
    videos, page_followers = _read_videos(ctx) if ctx.config.get("channel_url") else ([], None)
    if videos:
        save_videos(ctx, videos)
    if followers is None:
        followers = page_followers
    if followers is None and not videos:
        followers = _page_followers(ctx)
    if followers is None and data is None and not videos:
        raise SyncError("Rumble: " + (ctx.warnings[-1] if ctx.warnings else "no data source configured"))
    if followers is not None:
        ctx.channel.followers = followers
        ctx.stats["followers"] = followers
    ctx.metric("followers", followers, "Followers")
    if videos:
        ctx.metric("video_count", len({v["key"] for v in videos}), "Videos read from channel page")
    if not ctx.channel.url and ctx.config.get("channel_url"):
        ctx.channel.url = ctx.config["channel_url"]

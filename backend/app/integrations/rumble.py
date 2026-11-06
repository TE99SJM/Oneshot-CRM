"""Rumble: no public data API exists, so we combine two sources.

1. The official Live Stream API URL (rumble.com/account/livestream-api) gives followers,
   subscribers and live streams.
2. Fallback: the follower count shown on your public channel page.
"""
import re

from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, parse_dt, upsert_post

INFO = ProviderInfo(
    key="rumble", name="Rumble", platform="rumble", channel_kind="social",
    summary="Followers and subscribers, plus live streams if you use Rumble Live. Rumble has no public video stats API.",
    syncs=["Followers", "Subscribers (Live Stream API)", "Live streams (Live Stream API)"],
    fields=[
        FieldSpec("api_url", "Live Stream API URL", secret=True, required=False,
                  placeholder="https://rumble.com/-livestream-api/get-data?key=...",
                  help="Optional but recommended. Copy the full URL from rumble.com/account/livestream-api."),
        FieldSpec("channel_url", "Channel page URL", required=False, placeholder="https://rumble.com/c/YourChannel",
                  help="Used to read your public follower count if no API URL is set."),
    ],
    steps=[
        "Sign in at rumble.com and open rumble.com/account/livestream-api (Profile menu → Live Stream API).",
        "If no key is shown, click to generate one. Copy the whole URL, which starts with https://rumble.com/-livestream-api/get-data?key=",
        "Paste it in the Live Stream API URL box. Treat it like a password because anyone with it can read your stream data.",
        "Optionally add your channel page URL (for example https://rumble.com/c/YourChannel) as a backup for the follower count.",
        "Note: Rumble doesn't offer per-video view stats to outside apps, so add regular video stats on the Content page by hand.",
    ],
    docs_url="https://rumble.support/help/how-to-use-rumble-s-live-stream-api",
)

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
    resp = ctx.client.get(url, headers={"Accept": "text/html"})
    if resp.status_code == 403:
        ctx.warnings.append("Rumble blocked the channel page request (anti-bot check). Use the Live Stream API URL instead.")
        return None
    if resp.status_code >= 400:
        ctx.warnings.append(f"Rumble channel page returned HTTP {resp.status_code}.")
        return None
    m = FOLLOWERS_RE.search(resp.text)
    if not m:
        ctx.warnings.append("Couldn't find the follower count on the Rumble channel page.")
        return None
    return parse_count(m.group(1))


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
        for ls in data.get("livestreams") or []:
            if not isinstance(ls, dict) or not ls.get("id"):
                continue
            chat = ls.get("chat") or {}
            upsert_post(ctx, "rumble", f"live:{ls['id']}", title=ls.get("title") or "Rumble live stream",
                        published_at=parse_dt(ls.get("created_on")),
                        views=int(ls.get("watching_now") or 0),
                        likes=int(ls.get("likes") or 0),
                        comments=len(chat.get("recent_messages") or []) if isinstance(chat, dict) else 0)
    if followers is None:
        followers = _page_followers(ctx)
    if followers is None and data is None:
        raise SyncError("Rumble: " + (ctx.warnings[-1] if ctx.warnings else "no data source configured"))
    if followers is not None:
        ctx.channel.followers = followers
        ctx.stats["followers"] = followers
    if not ctx.channel.url and ctx.config.get("channel_url"):
        ctx.channel.url = ctx.config["channel_url"]

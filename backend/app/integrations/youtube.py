"""YouTube Data API v3 (API key): subscriber count + recent uploads with views/likes/comments."""
import base64
import ipaddress
import hashlib
import secrets as _secrets
from urllib.parse import parse_qs, urlencode, urlparse

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
        FieldSpec("oauth_client_id", "OAuth client ID (for posting)", required=False,
                  placeholder="1234-abc.apps.googleusercontent.com",
                  help="Only needed to upload videos from Compose. See “Set up posting” after saving."),
        FieldSpec("oauth_client_secret", "OAuth client secret (for posting)", secret=True, required=False,
                  placeholder="GOCSPX-...", help="From the same OAuth client (Desktop app type)."),
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
    ctx.stats["total_views"] = int(stats.get("viewCount", 0))      # lifetime channel views (all videos)
    if not stats.get("hiddenSubscriberCount"):
        ctx.metric("followers", stats.get("subscriberCount"), "Subscribers")
    ctx.metric("total_views", stats.get("viewCount"), "Lifetime channel views")
    ctx.metric("video_count", stats.get("videoCount"), "Public videos")

    _analytics(ctx)
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


# ---------------------------------------------------------------- YouTube Analytics (needs the Google sign-in)
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
# metric: (key, label, unit, section, combine)
CORE = [
    ("views", "yt_views_28d", "Views", "num", "Views", "sum"),
    ("estimatedMinutesWatched", "watch_minutes_28d", "Minutes watched", "minutes", "Watch time", "sum"),
    ("averageViewDuration", "avg_view_seconds_28d", "Average view duration", "seconds", "Watch time", "avg"),
    ("averageViewPercentage", "avg_view_pct_28d", "Average percentage viewed", "pct", "Watch time", "avg"),
    ("subscribersGained", "subs_gained_28d", "Subscribers gained", "num", "Audience", "sum"),
    ("subscribersLost", "subs_lost_28d", "Subscribers lost", "num", "Audience", "sum"),
    ("likes", "yt_likes_28d", "Likes", "num", "Engagement", "sum"),
    ("dislikes", "yt_dislikes_28d", "Dislikes", "num", "Engagement", "sum"),
    ("comments", "yt_comments_28d", "Comments", "num", "Engagement", "sum"),
    ("shares", "yt_shares_28d", "Shares", "num", "Engagement", "sum"),
    ("videosAddedToPlaylists", "playlist_adds_28d", "Added to playlists", "num", "Engagement", "sum"),
]
MONEY = [
    ("estimatedRevenue", "yt_revenue_28d", "Estimated revenue", "money", "Revenue", "sum"),
    ("estimatedAdRevenue", "yt_ad_revenue_28d", "Estimated ad revenue", "money", "Revenue", "sum"),
    ("grossRevenue", "yt_gross_revenue_28d", "Gross ad revenue", "money", "Revenue", "sum"),
    ("cpm", "yt_cpm_28d", "CPM", "money", "Revenue", "avg"),
    ("playbackBasedCpm", "yt_playback_cpm_28d", "Playback-based CPM", "money", "Revenue", "avg"),
    ("adImpressions", "yt_ad_impressions_28d", "Ad impressions", "num", "Revenue", "sum"),
    ("monetizedPlaybacks", "yt_monetized_playbacks_28d", "Monetized playbacks", "num", "Revenue", "sum"),
]
LIFETIME = [
    ("estimatedMinutesWatched", "watch_hours_all", "Watch hours (all time)", "hours", "Watch time", "sum"),
    ("subscribersGained", "subs_gained_all", "Subscribers gained (all time)", "num", "Audience", "sum"),
]


def _report(ctx, token: str, metrics: list, start: str, end: str) -> dict:
    r = ctx.client.get(ANALYTICS, headers={"Authorization": f"Bearer {token}"},
                       params={"ids": "channel==MINE", "startDate": start, "endDate": end,
                               "metrics": ",".join(m[0] for m in metrics)})
    data = check_response(r, "YouTube Analytics")
    heads = [h.get("name") for h in data.get("columnHeaders") or []]
    row = (data.get("rows") or [[0] * len(heads)])[0]
    return dict(zip(heads, row))


def _analytics(ctx: SyncContext) -> None:
    """Watch time, subscribers gained/lost, shares... (and revenue when the channel is monetized)."""
    from datetime import date, timedelta
    if not ctx.secrets.get("refresh_token"):
        ctx.warnings.append("For watch time, subscribers gained/lost, shares and revenue, sign in with Google "
                            "(Integrations → YouTube → “Set up posting”).")
        return
    try:
        token = access_token(ctx.client, ctx.config, ctx.secrets)
    except SyncError as e:
        ctx.warnings.append(f"YouTube Analytics skipped ({e}).")
        return
    end = date.today()
    start = (end - timedelta(days=27)).isoformat()
    try:
        vals = _report(ctx, token, CORE, start, end.isoformat())
    except SyncError as e:
        msg = str(e)
        if "403" in msg or "denied" in msg or "insufficient" in msg.lower() or "scope" in msg.lower():
            ctx.warnings.append("YouTube Analytics needs one more sign-in to allow it: Integrations → YouTube → "
                                "“Set up posting” and sign in again (adds watch time, subscribers gained, revenue).")
        else:
            ctx.warnings.append(f"YouTube Analytics unavailable ({msg}).")
        return
    for api_name, key, label, unit, section, combine in CORE:
        ctx.metric(key, vals.get(api_name), label, unit, section, "28d", combine)
    try:
        money = _report(ctx, token, MONEY, start, end.isoformat())
        for api_name, key, label, unit, section, combine in MONEY:
            ctx.metric(key, money.get(api_name), label, unit, section, "28d", combine)
    except SyncError:
        pass          # not in the YouTube Partner Program, or the money permission wasn't granted
    try:
        life = _report(ctx, token, LIFETIME, "2005-02-14", end.isoformat())
        ctx.metric("watch_hours_all", round(float(life.get("estimatedMinutesWatched") or 0) / 60, 1),
                   "Watch hours (all time)", "hours", "Watch time", "all", "sum")
        ctx.metric("subs_gained_all", life.get("subscribersGained"), "Subscribers gained (all time)", "num",
                   "Audience", "all", "sum")
    except SyncError:
        pass


# ---------------------------------------------------------------- posting sign-in (OAuth 2.0, installed-app flow)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_SCOPES = ("https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly "
                 "https://www.googleapis.com/auth/yt-analytics.readonly "
                 "https://www.googleapis.com/auth/yt-analytics-monetary.readonly")
REDIRECT_URI = "http://127.0.0.1"      # loopback redirect for "Desktop app" clients; the user pastes the address back
CALLBACK_PATH = "/api/oauth/youtube/callback"   # automatic return (needs a "Web application" client + public https host)


def normalize_redirect(value: str | None) -> str:
    """'' -> the copy/paste loopback address. Otherwise an https address on a real host name
    (Google refuses plain IP addresses like 100.x or 192.168.x and plain http)."""
    v = (value or "").strip().rstrip("/")
    if not v or v in (REDIRECT_URI, "http://localhost"):
        return REDIRECT_URI
    u = urlparse(v if "://" in v else f"https://{v}")
    host = (u.hostname or "").lower()
    if host in ("127.0.0.1", "localhost"):
        return REDIRECT_URI
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip or "." not in host:
        raise SyncError(f"Google won't send sign-ins back to {host or v}: it must be a web address with a name "
                        "(like https://mserver.your-tailnet.ts.net), not an IP address. Use your Tailscale Funnel "
                        "address, or choose “Copy and paste”.")
    if u.scheme != "https":
        raise SyncError("Google requires the return address to start with https:// (your Tailscale Funnel address does).")
    return f"https://{u.netloc}{CALLBACK_PATH}"


def new_pkce() -> tuple[str, str]:
    verifier = _secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(config: dict, challenge: str, state: str, redirect_uri: str = REDIRECT_URI) -> str:
    cid = (config.get("oauth_client_id") or "").strip()
    if not cid:
        raise SyncError("YouTube: enter the OAuth client ID and secret first (Edit the YouTube connection)")
    return AUTH_URL + "?" + urlencode({
        "client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "scope": UPLOAD_SCOPES,
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


def extract_code(pasted: str) -> str:
    v = (pasted or "").strip().strip('"').strip("'")
    if "error=access_denied" in v:
        raise SyncError("YouTube: the Google sign-in was cancelled. Try again and click Continue/Allow.")
    if "code=" in v:
        qs = urlparse(v).query if "://" in v else v.split("?", 1)[-1]
        code = (parse_qs(qs).get("code") or [""])[0]
        if code:
            return code
    if v.startswith("4/"):
        return v
    raise SyncError("YouTube: couldn't find the sign-in code. After clicking Continue, Google opens a new page "
                    "(it may not load). Copy that page's whole address bar (it contains “code=”) and paste it here.")


def _oauth_error(resp) -> str:
    try:
        body = resp.json()
        return f"{body.get('error', '')}: {body.get('error_description', '')}".strip(": ")
    except ValueError:
        return f"HTTP {resp.status_code}"


def exchange_code(client, config: dict, secrets: dict, code: str, verifier: str, redirect_uri: str = REDIRECT_URI) -> dict:
    resp = client.post(TOKEN_URL, data={
        "code": code, "client_id": config.get("oauth_client_id", "").strip(),
        "client_secret": secrets.get("oauth_client_secret", "").strip(), "redirect_uri": redirect_uri,
        "grant_type": "authorization_code", "code_verifier": verifier})
    if resp.status_code >= 400:
        err = _oauth_error(resp)
        hint = ""
        if "redirect_uri_mismatch" in err:
            hint = (f" Google Cloud must list exactly {redirect_uri} under the client's Authorized redirect URIs"
                    if redirect_uri != REDIRECT_URI else " This client needs to be a “Desktop app” for copy and paste")
        elif "invalid_client" in err or "unauthorized_client" in err:
            hint = " Check the client ID and secret were copied from the same Google client."
        raise SyncError(f"YouTube sign-in failed ({err}).{hint} Codes expire after a few minutes; try again.")
    data = resp.json()
    if not data.get("refresh_token"):
        raise SyncError("YouTube: Google didn't return a long-term token. Remove the app's access at "
                        "myaccount.google.com/permissions and sign in again.")
    return data


def access_token(client, config: dict, secrets: dict) -> str:
    if not secrets.get("refresh_token"):
        raise SyncError("YouTube: posting isn't set up. Integrations → YouTube → “Set up posting”.")
    resp = client.post(TOKEN_URL, data={
        "client_id": config.get("oauth_client_id", "").strip(), "client_secret": secrets.get("oauth_client_secret", "").strip(),
        "refresh_token": secrets["refresh_token"], "grant_type": "refresh_token"})
    if resp.status_code >= 400:
        err = _oauth_error(resp)
        if "invalid_grant" in err:
            raise SyncError("YouTube: the posting sign-in expired or was revoked. Click “Set up posting” and sign in "
                            "again. If this happens every week, set your Google app's Audience to “In production”.")
        raise SyncError(f"YouTube: couldn't refresh the posting sign-in ({err})")
    return resp.json()["access_token"]


def my_channel(client, token: str) -> dict:
    resp = client.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {token}"})
    items = (check_response(resp, "YouTube").get("items") or [])
    return items[0] if items else {}

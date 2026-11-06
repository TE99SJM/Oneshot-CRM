"""Facebook Page via Graph API: followers + recent posts (reactions, comments, shares, views)."""
from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, parse_dt, upsert_post

DEFAULT_VERSION = "v27.0"

INFO = ProviderInfo(
    key="facebook", name="Facebook Page", platform="facebook", channel_kind="social",
    summary="Page followers and your recent posts with reactions, comments, shares and views.",
    syncs=["Page followers", "Recent posts (reactions, comments, shares)", "Post views (needs read_insights)"],
    fields=[
        FieldSpec("page_id", "Page ID", placeholder="1234567890",
                  help="Numeric Page ID (shown in the me/accounts result, or Page → About → Page transparency)."),
        FieldSpec("page_token", "Page access token", secret=True, placeholder="EAA...",
                  help="A long-lived Page token with pages_read_engagement (and read_insights for views)."),
        FieldSpec("max_posts", "Posts to sync", required=False, default="100", placeholder="100"),
        FieldSpec("api_version", "Graph API version", required=False, default=DEFAULT_VERSION, placeholder=DEFAULT_VERSION,
                  help="Leave as is unless Meta retires this version."),
    ],
    steps=[
        "Go to developers.facebook.com → My Apps → Create app. Choose “Other”, then “Business” (any name). Use the Facebook account that manages the Page.",
        "Open Tools → Graph API Explorer. Pick your app under “Meta App”.",
        "Under Permissions add pages_show_list, pages_read_engagement and read_insights, then click Generate Access Token and approve your Page.",
        "Make it long-lived: open Tools → Access Token Debugger, paste the token, click “Extend Access Token” and copy the new token.",
        "Back in Graph API Explorer, paste that long-lived token, run GET me/accounts, and copy your Page's “id” and “access_token”. That Page token does not expire.",
        "Paste the Page ID and Page access token here.",
    ],
    docs_url="https://developers.facebook.com/docs/pages-api/overview",
)


def _base(ctx: SyncContext) -> str:
    return f"https://graph.facebook.com/{(ctx.config.get('api_version') or DEFAULT_VERSION).strip()}"


def _get(ctx: SyncContext, path: str, **params):
    params["access_token"] = ctx.secrets.get("page_token", "")
    return check_response(ctx.client.get(f"{_base(ctx)}/{path}", params=params), "Facebook")


def _page(ctx: SyncContext) -> dict:
    page_id = (ctx.config.get("page_id") or "").strip()
    if not page_id:
        raise SyncError("Facebook: enter the Page ID")
    return _get(ctx, page_id, fields="id,name,link,followers_count,fan_count")


def test(ctx: SyncContext) -> str:
    p = _page(ctx)
    return f"Connected to {p.get('name')} ({p.get('followers_count', p.get('fan_count', 0))} followers)"


POST_FIELDS = ("id,message,story,created_time,permalink_url,shares,"
               "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)")


def sync(ctx: SyncContext) -> None:
    page = _page(ctx)
    ctx.channel.followers = int(page.get("followers_count") or page.get("fan_count") or 0)
    ctx.channel.url = ctx.channel.url or page.get("link", "")
    ctx.channel.handle = ctx.channel.handle or page.get("name", "")
    ctx.stats["followers"] = ctx.channel.followers

    limit = max(1, min(int(ctx.config.get("max_posts") or 100), 500))
    posts: list[dict] = []
    params = {"fields": POST_FIELDS, "limit": 50}
    data = _get(ctx, f"{page['id']}/posts", **params)
    while True:
        posts += data.get("data", [])
        nxt = data.get("paging", {}).get("next")
        if not nxt or len(posts) >= limit:
            break
        data = check_response(ctx.client.get(nxt), "Facebook")
    posts = posts[:limit]

    insights_ok = True
    for p in posts:
        views = 0
        if insights_ok:
            try:
                ins = _get(ctx, f"{p['id']}/insights", metric="post_media_view", period="lifetime")
                for m in ins.get("data", []):
                    vals = m.get("values") or [{}]
                    views = int(vals[0].get("value") or 0)
            except SyncError as e:
                insights_ok = False   # missing read_insights or metric unavailable: keep syncing without views
                ctx.warnings.append(f"Post views unavailable ({e}). Add the read_insights permission to get views.")
        text = p.get("message") or p.get("story") or ""
        upsert_post(ctx, "facebook", p["id"], title=(text.split("\n")[0] or "Facebook post")[:200], body=text,
                    url=p.get("permalink_url", ""), published_at=parse_dt(p.get("created_time")), views=views,
                    likes=p.get("reactions", {}).get("summary", {}).get("total_count", 0),
                    comments=p.get("comments", {}).get("summary", {}).get("total_count", 0),
                    shares=(p.get("shares") or {}).get("count", 0))

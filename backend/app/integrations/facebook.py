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
                  help="A long-lived Page token with pages_read_engagement, read_insights (views) and pages_manage_posts (posting)."),
        FieldSpec("max_posts", "Posts to sync", required=False, default="100", placeholder="100"),
        FieldSpec("api_version", "Graph API version", required=False, default=DEFAULT_VERSION, placeholder=DEFAULT_VERSION,
                  help="Leave as is unless Meta retires this version."),
    ],
    steps=[
        "Go to developers.facebook.com → My Apps → Create app. Choose “Other”, then “Business” (any name). Use the Facebook account that manages the Page.",
        "Open Tools → Graph API Explorer. Pick your app under “Meta App”.",
        "Under Permissions add pages_show_list, pages_read_engagement, read_insights and pages_manage_posts (needed to post from Compose), then click Generate Access Token and approve your Page.",
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
    try:
        return _get(ctx, page_id, fields="id,name,link,followers_count,fan_count," + PAGE_EXTRA)
    except SyncError:
        return _get(ctx, page_id, fields="id,name,link,followers_count,fan_count")


PAGE_EXTRA = "talking_about_count,checkins,rating_count,overall_star_rating,new_like_count,were_here_count"
# Page Insights (needs read_insights), 28-day totals. Meta retires metrics now and then; missing ones are skipped.
INSIGHTS = [
    ("page_media_view", "fb_media_views_28d", "Content views", "Views", "sum"),
    ("page_total_media_view_unique", "fb_viewers_28d", "Viewers (unique)", "Views", "sum"),
    ("page_impressions", "fb_impressions_28d", "Impressions", "Views", "sum"),
    ("page_posts_impressions", "fb_post_impressions_28d", "Post impressions", "Views", "sum"),
    ("page_post_engagements", "fb_engagements_28d", "Post engagements", "Engagement", "sum"),
    ("page_total_actions", "fb_actions_28d", "Clicks on Page actions (call, website, directions)", "Engagement", "sum"),
    ("page_views_total", "fb_page_views_28d", "Page profile views", "Views", "sum"),
    ("page_video_views", "fb_video_views_28d", "Video views (3 seconds+)", "Views", "sum"),
    ("page_video_complete_views_30s", "fb_video_30s_views_28d", "Video views (30 seconds+)", "Views", "sum"),
    ("page_daily_follows_unique", "fb_new_follows_28d", "New follows", "Audience", "sum"),
    ("page_daily_unfollows_unique", "fb_unfollows_28d", "Unfollows", "Audience", "sum"),
    ("page_fan_adds_unique", "fb_new_likes_28d", "New Page likes", "Audience", "sum"),
    ("page_fan_removes_unique", "fb_unlikes_28d", "Page unlikes", "Audience", "sum"),
    ("page_actions_post_reactions_like_total", "fb_like_reactions_28d", "Like reactions", "Engagement", "sum"),
    ("page_actions_post_reactions_love_total", "fb_love_reactions_28d", "Love reactions", "Engagement", "sum"),
]


def _insight_value(item: dict):
    vals = item.get("values") or []
    v = vals[-1].get("value") if vals else None
    if isinstance(v, dict):
        v = sum(x for x in v.values() if isinstance(x, (int, float)))
    return v


def _page_metrics(ctx: SyncContext, page: dict) -> None:
    ctx.metric("followers", page.get("followers_count") or page.get("fan_count"), "Page followers")
    ctx.metric("page_likes", page.get("fan_count"), "Page likes")
    ctx.metric("talking_about", page.get("talking_about_count"))
    ctx.metric("fb_checkins", page.get("checkins"), "Check-ins", "num", "Audience")
    ctx.metric("fb_were_here", page.get("were_here_count"), "People who were here", "num", "Audience")
    ctx.metric("fb_new_likes", page.get("new_like_count"), "New likes since last check", "num", "Audience")
    ctx.metric("fb_rating_count", page.get("rating_count"), "Reviews", "num", "Audience")
    ctx.metric("fb_star_rating", page.get("overall_star_rating"), "Star rating", "stars", "Audience", combine="avg")
    names = [m[0] for m in INSIGHTS]
    found: dict = {}
    try:
        data = _get(ctx, f"{page['id']}/insights", metric=",".join(names), period="days_28")
        found = {i.get("name"): _insight_value(i) for i in data.get("data", [])}
    except SyncError:
        for n in names:                       # one retired metric fails the whole request: ask one by one
            try:
                data = _get(ctx, f"{page['id']}/insights", metric=n, period="days_28")
                for i in data.get("data", []):
                    found[i.get("name")] = _insight_value(i)
            except SyncError as e:
                if "permission" in str(e).lower() or "read_insights" in str(e):
                    ctx.warnings.append("Page Insights need the read_insights permission on the Page token.")
                    break
    for api_name, key, label, section, combine in INSIGHTS:
        ctx.metric(key, found.get(api_name), label, "num", section, "28d", combine)


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
    _page_metrics(ctx, page)

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

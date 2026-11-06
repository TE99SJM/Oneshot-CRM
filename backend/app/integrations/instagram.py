"""Instagram professional (Business/Creator) account via the Graph API.

Uses the same Page access token as the Facebook integration: Page -> instagram_business_account -> IG user.
"""
from .base import FieldSpec, ProviderInfo, SyncContext, SyncError, check_response, parse_dt, upsert_post
from .facebook import DEFAULT_VERSION

INFO = ProviderInfo(
    key="instagram", name="Instagram", platform="instagram", channel_kind="social",
    summary="Followers and your recent posts/reels with likes and comments. Needs a Business or Creator account linked to your Facebook Page.",
    syncs=["Followers", "Recent posts and reels (likes, comments)", "Views when Instagram provides them"],
    fields=[
        FieldSpec("page_id", "Facebook Page ID", placeholder="1234567890",
                  help="The Facebook Page your Instagram account is linked to (same ID as the Facebook connection)."),
        FieldSpec("page_token", "Page access token", secret=True, placeholder="EAA...",
                  help="The same long-lived Page token as Facebook, with instagram_basic added."),
        FieldSpec("max_posts", "Posts to sync", required=False, default="100", placeholder="100"),
        FieldSpec("api_version", "Graph API version", required=False, default=DEFAULT_VERSION, placeholder=DEFAULT_VERSION),
    ],
    steps=[
        "In the Instagram app: Settings → Account type and tools → Switch to professional account (Creator or Business). It's free.",
        "Link it to your Facebook Page: on the Page go to Settings → Linked accounts → Instagram → Connect.",
        "Make the Page token like in the Facebook steps (Graph API Explorer), but also tick instagram_basic and instagram_manage_insights before Generate Access Token.",
        "Extend the token in the Access Token Debugger, then run GET me/accounts and copy the Page id and access_token.",
        "Paste the Page ID and token here. If you already connected Facebook with these permissions, you can reuse the same token.",
    ],
    docs_url="https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login",
)


def _base(ctx):
    return f"https://graph.facebook.com/{(ctx.config.get('api_version') or DEFAULT_VERSION).strip()}"


def _get(ctx, path, **params):
    params["access_token"] = ctx.secrets.get("page_token", "")
    return check_response(ctx.client.get(f"{_base(ctx)}/{path}", params=params), "Instagram")


def _account(ctx) -> dict:
    page_id = (ctx.config.get("page_id") or "").strip()
    if not page_id:
        raise SyncError("Instagram: enter the Facebook Page ID")
    page = _get(ctx, page_id, fields="instagram_business_account")
    ig = (page.get("instagram_business_account") or {}).get("id")
    if not ig:
        raise SyncError("Instagram: no professional Instagram account is linked to this Page "
                        "(or the token is missing instagram_basic)")
    return _get(ctx, ig, fields="id,username,followers_count,media_count")


def test(ctx: SyncContext) -> str:
    a = _account(ctx)
    return f"Connected to @{a.get('username')} ({a.get('followers_count', 0)} followers)"


def sync(ctx: SyncContext) -> None:
    a = _account(ctx)
    ctx.channel.followers = int(a.get("followers_count") or 0)
    if a.get("username"):
        ctx.channel.handle = ctx.channel.handle or f"@{a['username']}"
        ctx.channel.url = ctx.channel.url or f"https://www.instagram.com/{a['username']}/"
    ctx.stats["followers"] = ctx.channel.followers
    limit = max(1, min(int(ctx.config.get("max_posts") or 100), 500))
    fields = "id,caption,media_type,permalink,timestamp,like_count,comments_count"
    try:
        data = _get(ctx, f"{a['id']}/media", fields=fields + ",view_count", limit=50)
    except SyncError:
        data = _get(ctx, f"{a['id']}/media", fields=fields, limit=50)   # older versions lack view_count
    media: list[dict] = []
    while True:
        media += data.get("data", [])
        nxt = data.get("paging", {}).get("next")
        if not nxt or len(media) >= limit:
            break
        data = check_response(ctx.client.get(nxt), "Instagram")
    for m in media[:limit]:
        caption = m.get("caption") or ""
        upsert_post(ctx, "instagram", m["id"],
                    title=(caption.split("\n")[0] or f"Instagram {m.get('media_type', 'post').lower()}")[:200],
                    body=caption, url=m.get("permalink", ""), published_at=parse_dt(m.get("timestamp")),
                    views=m.get("view_count", 0) or 0, likes=m.get("like_count", 0) or 0,
                    comments=m.get("comments_count", 0) or 0)

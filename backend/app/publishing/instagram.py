"""Post to Instagram (professional account): a photo, a carousel of photos, or a Reel.

Instagram fetches photos from a public address. If the CRM has no public address, photos are staged as
unpublished (hidden) Facebook Page photos and Instagram fetches them from Facebook's servers; the staged
copies are deleted afterwards. Videos are uploaded directly (resumable upload), with a public-address fallback.
"""
from ..integrations.base import SyncContext, SyncError
from . import common
from .common import UPLOAD_TIMEOUT, PublishInput, PublishResult, checked, clip, file_chunks, file_path
from .facebook import base_url, call, page_id, token, upload_unpublished_photo
from . import media as media_store

HINT = ("The Page token needs instagram_basic, instagram_content_publish and pages_manage_posts "
        "(Integrations → Instagram → Edit, see “How to get these details”).")
MAX_ITEMS = 20


def validate(item: PublishInput) -> list[str]:
    errs = []
    if not item.media:
        errs.append("Instagram needs at least one photo or a video.")
    if item.videos and (len(item.videos) > 1 or item.images):
        errs.append("Instagram: post one video on its own (as a Reel), or up to 20 photos.")
    if len(item.images) > MAX_ITEMS:
        errs.append(f"Instagram: up to {MAX_ITEMS} photos per post.")
    if len(item.text_with_link()) > 2200:
        errs.append("Instagram captions are limited to 2,200 characters.")
    return errs


def _ig(ctx, method, path, **kw):
    return call(ctx, method, path, platform="Instagram", hint=HINT, **kw)


def _account(ctx: SyncContext) -> str:
    page = _ig(ctx, "GET", page_id(ctx), params={"fields": "instagram_business_account"})
    ig = (page.get("instagram_business_account") or {}).get("id")
    if not ig:
        raise SyncError("Instagram: no professional Instagram account is linked to this Facebook Page")
    return ig


def _wait(ctx: SyncContext, container: str, video: bool) -> None:
    interval, tries = (10, 90) if video else (3, 40)       # up to 15 min for video, 2 min for photos
    for _ in range(tries):
        st = _ig(ctx, "GET", container, params={"fields": "status_code,status"})
        code = st.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise SyncError(f"Instagram couldn't process the media ({st.get('status') or code}). "
                            "Check it meets Instagram's format rules (JPEG photos; MP4/MOV video, 3s–15min).")
        common.sleep(interval)
    raise SyncError("Instagram: still processing after waiting. It may appear later; check Instagram before retrying.")


def _photo_urls(ctx: SyncContext, item: PublishInput, staged: list[str]) -> list[str]:
    urls = []
    for m in item.images:
        if item.public_base:
            urls.append(item.public_url(m))
            continue
        photo_id = upload_unpublished_photo(ctx, file_path(m) if not m.jpeg_name else media_store.jpeg_path_of(m),
                                            m.filename, platform="Instagram", hint=HINT)
        staged.append(photo_id)
        images = _ig(ctx, "GET", photo_id, params={"fields": "images"}).get("images") or []
        if not images:
            raise SyncError("Instagram: couldn't get a link to the staged photo from Facebook")
        urls.append(max(images, key=lambda i: i.get("width", 0))["source"])
    return urls


def publish(ctx: SyncContext, item: PublishInput) -> PublishResult:
    ig = _account(ctx)
    caption = clip(item.text_with_link(), 2200)
    staged: list[str] = []
    try:
        if item.videos:
            container = _video_container(ctx, item, ig, caption)
            _wait(ctx, container, video=True)
        else:
            urls = _photo_urls(ctx, item, staged)
            if len(urls) == 1:
                container = _ig(ctx, "POST", f"{ig}/media", data={"image_url": urls[0], "caption": caption})["id"]
            else:
                children = [_ig(ctx, "POST", f"{ig}/media", data={"image_url": u, "is_carousel_item": "true"})["id"]
                            for u in urls]
                for c in children:
                    _wait(ctx, c, video=False)
                container = _ig(ctx, "POST", f"{ig}/media", data={"media_type": "CAROUSEL", "caption": caption,
                                                                  "children": ",".join(children)})["id"]
            _wait(ctx, container, video=False)
        media_id = _ig(ctx, "POST", f"{ig}/media_publish", data={"creation_id": container})["id"]
    finally:
        for pid in staged:                        # remove the hidden staging copies from the Facebook Page
            try:
                _ig(ctx, "DELETE", pid)
            except Exception:
                pass
    try:
        url = _ig(ctx, "GET", media_id, params={"fields": "permalink"}).get("permalink", "")
    except SyncError:
        url = ""
    return PublishResult(media_id, url)


def _video_container(ctx: SyncContext, item: PublishInput, ig: str, caption: str) -> str:
    m = item.videos[0]
    path = file_path(m)
    base = {"media_type": "REELS", "caption": caption,
            "share_to_feed": "true" if item.options.get("share_to_feed", True) else "false"}
    try:
        r = _ig(ctx, "POST", f"{ig}/media", data={**base, "upload_type": "resumable"})
        container = r["id"]
        uri = r.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{base_url(ctx).rsplit('/', 1)[-1]}/{container}"
        if not uri.startswith("https://rupload.facebook.com/"):
            raise SyncError("Instagram: unexpected upload address")
        size = path.stat().st_size
        checked(ctx.client.post(uri, content=file_chunks(path), timeout=UPLOAD_TIMEOUT, headers={
            "Authorization": f"OAuth {token(ctx)}", "offset": "0", "file_size": str(size),
            "Content-Length": str(size), "Content-Type": "application/octet-stream"}), "Instagram", HINT)
        return container
    except SyncError as direct_err:
        if not item.public_base:
            raise SyncError(f"{direct_err}. Instagram didn't accept a direct video upload; as a fallback, set a "
                            "public media address on the Instagram connection (see README “Posting”).") from None
    return _ig(ctx, "POST", f"{ig}/media", data={**base, "video_url": item.public_url(m)})["id"]

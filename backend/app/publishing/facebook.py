"""Post to a Facebook Page: text/link, one or more photos, a feed video, or a Reel."""
from ..integrations.base import SyncContext, SyncError
from ..integrations.facebook import DEFAULT_VERSION
from .common import UPLOAD_TIMEOUT, PublishInput, PublishResult, checked, clip, file_chunks, file_path, read_range

HINT = ("Make a new Page token with the pages_manage_posts permission (Integrations → Facebook → Edit, "
        "see “How to get these details”).")
MAX_PHOTOS = 20


def validate(item: PublishInput) -> list[str]:
    errs = []
    if not (item.text.strip() or item.link.strip() or item.media):
        errs.append("Facebook needs some text, a link, or a photo/video.")
    if len(item.videos) > 1:
        errs.append("Facebook takes one video per post.")
    if item.videos and item.images:
        errs.append("Facebook can't mix photos and a video in one post. Post them separately.")
    if len(item.images) > MAX_PHOTOS:
        errs.append(f"Facebook: up to {MAX_PHOTOS} photos per post.")
    return errs


def base_url(ctx: SyncContext) -> str:
    return f"https://graph.facebook.com/{(ctx.config.get('api_version') or DEFAULT_VERSION).strip()}"


def page_id(ctx: SyncContext) -> str:
    pid = (ctx.config.get("page_id") or "").strip()
    if not pid:
        raise SyncError("Facebook: the connection has no Page ID")
    return pid


def token(ctx: SyncContext) -> str:
    t = ctx.secrets.get("page_token", "")
    if not t:
        raise SyncError("Facebook: the connection has no Page access token")
    return t


def call(ctx: SyncContext, method: str, path: str, *, data=None, files=None, params=None, platform="Facebook",
         hint=HINT, timeout=None):
    url = path if path.startswith("http") else f"{base_url(ctx)}/{path}"
    kw = {"timeout": timeout} if timeout else {}
    if method == "GET":
        resp = ctx.client.get(url, params={**(params or {}), "access_token": token(ctx)}, **kw)
    elif method == "DELETE":
        resp = ctx.client.delete(url, params={"access_token": token(ctx)}, **kw)
    else:
        resp = ctx.client.post(url, data={**(data or {}), "access_token": token(ctx)}, files=files, **kw)
    return checked(resp, platform, hint)


def upload_unpublished_photo(ctx: SyncContext, path, filename: str, platform="Facebook", hint=HINT) -> str:
    with path.open("rb") as f:
        r = call(ctx, "POST", f"{page_id(ctx)}/photos", data={"published": "false"},
                 files={"source": (filename, f, "image/jpeg")}, platform=platform, hint=hint, timeout=UPLOAD_TIMEOUT)
    return r["id"]


def _permalink(ctx: SyncContext, object_id: str, default: str) -> str:
    try:
        link = call(ctx, "GET", object_id, params={"fields": "permalink_url"}).get("permalink_url") or ""
    except SyncError:
        return default
    return f"https://www.facebook.com{link}" if link.startswith("/") else (link or default)


def publish(ctx: SyncContext, item: PublishInput) -> PublishResult:
    pid = page_id(ctx)
    if item.videos:
        return _video(ctx, item, pid)
    if len(item.images) == 1:
        m = item.images[0]
        with file_path(m).open("rb") as f:
            r = call(ctx, "POST", f"{pid}/photos", data={"message": item.text_with_link()},
                     files={"source": (m.filename, f, m.mime or "image/jpeg")}, timeout=UPLOAD_TIMEOUT)
        post_id = r.get("post_id") or r["id"]
        return PublishResult(post_id, _permalink(ctx, post_id, f"https://www.facebook.com/{post_id}"))
    if item.images:
        ids = [upload_unpublished_photo(ctx, file_path(m), m.filename) for m in item.images]
        data = {"message": item.text_with_link()}
        for i, fbid in enumerate(ids):
            data[f"attached_media[{i}]"] = f'{{"media_fbid":"{fbid}"}}'
        r = call(ctx, "POST", f"{pid}/feed", data=data)
        return PublishResult(r["id"], _permalink(ctx, r["id"], f"https://www.facebook.com/{r['id']}"))
    data = {"message": item.text}
    if item.link:
        data["link"] = item.link
    r = call(ctx, "POST", f"{pid}/feed", data=data)
    return PublishResult(r["id"], _permalink(ctx, r["id"], f"https://www.facebook.com/{r['id']}"))


def _video(ctx: SyncContext, item: PublishInput, pid: str) -> PublishResult:
    m = item.videos[0]
    path = file_path(m)
    size = path.stat().st_size
    description = item.text_with_link()
    if item.options.get("as_reel"):
        start = call(ctx, "POST", f"{pid}/video_reels", data={"upload_phase": "start"})
        vid = start["video_id"]
        upload_url = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{base_url(ctx).rsplit('/', 1)[-1]}/{vid}"
        if not upload_url.startswith("https://rupload.facebook.com/"):
            raise SyncError("Facebook: unexpected Reel upload address")
        resp = ctx.client.post(upload_url, content=file_chunks(path), timeout=UPLOAD_TIMEOUT, headers={
            "Authorization": f"OAuth {token(ctx)}", "offset": "0", "file_size": str(size),
            "Content-Length": str(size), "Content-Type": "application/octet-stream"})
        checked(resp, "Facebook", HINT)
        call(ctx, "POST", f"{pid}/video_reels", data={"upload_phase": "finish", "video_id": vid,
                                                      "video_state": "PUBLISHED", "description": description})
        return PublishResult(vid, f"https://www.facebook.com/reel/{vid}", status="processing",
                             note="Facebook is processing the Reel; it appears on the Page in a few minutes.")

    start = call(ctx, "POST", f"{pid}/videos", data={"upload_phase": "start", "file_size": str(size)})
    session, vid = start["upload_session_id"], start.get("video_id", "")
    s, e = int(start["start_offset"]), int(start["end_offset"])
    while s < e:
        chunk = read_range(path, s, e)
        r = call(ctx, "POST", f"{pid}/videos", data={"upload_phase": "transfer", "upload_session_id": session,
                                                     "start_offset": str(s)},
                 files={"video_file_chunk": (m.filename, chunk, "application/octet-stream")}, timeout=UPLOAD_TIMEOUT)
        ns, ne = int(r["start_offset"]), int(r["end_offset"])
        if ns <= s and ns != ne:
            raise SyncError("Facebook: the video upload stopped making progress. Try again.")
        s, e = ns, ne
    data = {"upload_phase": "finish", "upload_session_id": session, "description": description}
    title = clip(item.options.get("title") or item.title, 255)
    if title:
        data["title"] = title
    call(ctx, "POST", f"{pid}/videos", data=data)
    url = _permalink(ctx, vid, f"https://www.facebook.com/{pid}/videos/{vid}") if vid else ""
    return PublishResult(vid or session, url, status="processing",
                         note="Facebook is processing the video; it appears on the Page in a few minutes.")

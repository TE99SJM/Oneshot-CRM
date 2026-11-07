"""Post to TikTok with the Content Posting API.

* Video, Direct Post: creator_info → video/init (FILE_UPLOAD) → PUT chunks → poll status.
* Video, Send to TikTok inbox as a draft (video.upload scope): the TikTok app notifies you to finish and post it.
* Photos (Direct Post or draft): content/init with PULL_FROM_URL. TikTok downloads the photos from your public
  https address, which you must verify in the TikTok developer portal (URL prefix) first.

Docs: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post ,
https://developers.tiktok.com/doc/content-posting-api-reference-upload-video ,
https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide ,
https://developers.tiktok.com/doc/content-sharing-guidelines
"""
from ..integrations import tiktok as tt
from ..integrations.base import SyncContext, SyncError
from . import common
from .common import UPLOAD_TIMEOUT, PublishInput, PublishResult, clip, file_path, read_range

PRIVACY = {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
MIN_CHUNK, CHUNK = 5 * 1024 * 1024, 10 * 1024 * 1024
POLL_SECONDS, POLL_TRIES = 5, 60


def creator_info(ctx: SyncContext) -> dict:
    token = tt.access_token(ctx)
    return tt.api_post(ctx.client, token, "/post/publish/creator_info/query/", {}, what="TikTok")


def _opt(item: PublishInput, key: str, default=None):
    return item.options.get(key, default)


def validate(item: PublishInput) -> list[str]:
    errs = []
    mode = _opt(item, "mode", "direct")
    if item.videos and item.images:
        errs.append("TikTok: post one video, or up to 35 photos, not both.")
    elif len(item.videos) > 1:
        errs.append("TikTok takes one video per post.")
    elif not item.videos and not item.images:
        errs.append("TikTok needs a video or photos.")
    if len(item.images) > 35:
        errs.append("TikTok photo posts take up to 35 photos.")
    if mode == "direct":
        if _opt(item, "privacy_level") not in PRIVACY:
            errs.append("TikTok: choose who can view the post (TikTok requires you to pick it each time).")
        if _opt(item, "brand_content") and _opt(item, "privacy_level") == "SELF_ONLY":
            errs.append("TikTok: branded content can't be private (Only me).")
        if not _opt(item, "consent"):
            errs.append("TikTok: tick the box agreeing to TikTok's Music Usage Confirmation.")
    if _opt(item, "disclose") and not (_opt(item, "brand_organic") or _opt(item, "brand_content")):
        errs.append("TikTok: you turned on content disclosure, so pick “Your brand”, “Branded content”, or both.")
    return errs


def _post_info(item: PublishInput, info: dict, photo: bool) -> dict:
    text = item.text_with_link()
    pi = {
        "privacy_level": _opt(item, "privacy_level", "SELF_ONLY"),
        "disable_comment": not _opt(item, "allow_comment", False) or bool(info.get("comment_disabled")),
        "brand_content_toggle": bool(_opt(item, "brand_content", False)),
        "brand_organic_toggle": bool(_opt(item, "brand_organic", False)),
    }
    if photo:
        pi["title"] = clip(item.options.get("title") or item.title or "", 90)
        pi["description"] = clip(text, 4000)
        pi["auto_add_music"] = bool(_opt(item, "auto_add_music", True))
    else:
        pi["title"] = clip(text or item.title, 2200)            # for videos the "title" is the caption
        pi["disable_duet"] = not _opt(item, "allow_duet", False) or bool(info.get("duet_disabled"))
        pi["disable_stitch"] = not _opt(item, "allow_stitch", False) or bool(info.get("stitch_disabled"))
        if _opt(item, "is_aigc"):
            pi["is_aigc"] = True
    return pi


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) per TikTok's media transfer rules: chunks of 5-64 MB, the last chunk
    takes the remainder (up to 128 MB); files up to 64 MB go in one piece."""
    if size <= 64 * 1024 * 1024:                # TikTok accepts files up to 64 MB as one piece
        return size, 1
    return CHUNK, max(1, size // CHUNK)


def _upload(ctx: SyncContext, upload_url: str, path, size: int, mime: str) -> None:
    chunk, count = chunk_plan(size)
    for n in range(count):
        start = n * chunk
        end = size if n == count - 1 else start + chunk
        resp = ctx.client.put(upload_url, content=read_range(path, start, end), timeout=UPLOAD_TIMEOUT,
                              headers={"Content-Type": mime or "video/mp4", "Content-Length": str(end - start),
                                       "Content-Range": f"bytes {start}-{end - 1}/{size}"})
        if resp.status_code not in (200, 201, 206):
            raise SyncError(f"TikTok: upload of part {n + 1}/{count} failed (HTTP {resp.status_code}) {resp.text[:200]}")


def _wait(ctx: SyncContext, token: str, publish_id: str, mode: str) -> PublishResult:
    status, data = "", {}
    for _ in range(POLL_TRIES):
        data = tt.api_post(ctx.client, token, "/post/publish/status/fetch/", {"publish_id": publish_id})
        status = data.get("status", "")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"):
            break
        common.sleep(POLL_SECONDS)
    if status == "FAILED":
        raise SyncError(f"TikTok couldn't post it: {data.get('fail_reason') or 'unknown reason'}")
    ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
    if status == "SEND_TO_USER_INBOX" or mode == "draft":
        return PublishResult(publish_id, "", status="posted",
                             note="Sent to your TikTok inbox. Open the TikTok app and tap the notification to finish posting.")
    if status == "PUBLISH_COMPLETE":
        vid = str(ids[0]) if ids else ""
        user = ctx.config.get("username") or ""
        url = f"https://www.tiktok.com/@{user}/video/{vid}" if vid and user and " " not in user else ""
        note = "" if ids else "Posted. Private (Only me) posts don't get a public link."
        return PublishResult(vid or publish_id, url, status="posted", note=note)
    return PublishResult(publish_id, "", status="processing",
                         note="TikTok is still processing it; check the TikTok app in a few minutes.")


def publish(ctx: SyncContext, item: PublishInput) -> PublishResult:
    token = tt.access_token(ctx)
    mode = _opt(item, "mode", "direct")
    info = creator_info(ctx) if mode == "direct" else {}
    if mode == "direct":
        allowed = info.get("privacy_level_options") or []
        if allowed and _opt(item, "privacy_level") not in allowed:
            raise SyncError(f"TikTok: your account currently allows these visibility options only: {', '.join(allowed)}. "
                            "Unaudited apps can only post as Only me (SELF_ONLY).")

    if item.images:
        if not item.public_base:
            raise SyncError("TikTok photo posts need a public https address that TikTok can download the photos from. "
                            "Set the Instagram public address or the Tailscale Funnel for /api/media, and verify it in "
                            "the TikTok developer portal (URL prefix). Videos don't need this.")
        body = {"post_info": _post_info(item, info, photo=True),
                "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0,
                                "photo_images": [item.public_url(m) for m in item.images[:35]]},
                "post_mode": "DIRECT_POST" if mode == "direct" else "MEDIA_UPLOAD", "media_type": "PHOTO"}
        if mode != "direct":
            body["post_info"] = {k: v for k, v in body["post_info"].items() if k in ("title", "description")}
        data = tt.api_post(ctx.client, token, "/post/publish/content/init/", body)
        return _wait(ctx, token, data["publish_id"], mode)

    m = item.videos[0]
    path = file_path(m)
    size = path.stat().st_size
    max_sec = int(info.get("max_video_post_duration_sec") or 0)
    dur = getattr(m, "duration", 0) or 0
    if max_sec and dur and dur > max_sec:
        raise SyncError(f"TikTok: your account can post videos up to {max_sec // 60} min {max_sec % 60} s long.")
    chunk, count = chunk_plan(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}
    if mode == "direct":
        data = tt.api_post(ctx.client, token, "/post/publish/video/init/",
                           {"post_info": _post_info(item, info, photo=False), "source_info": source})
    else:
        data = tt.api_post(ctx.client, token, "/post/publish/inbox/video/init/", {"source_info": source})
    if not data.get("upload_url") or not data.get("publish_id"):
        raise SyncError("TikTok didn't return an upload address")
    _upload(ctx, data["upload_url"], path, size, m.mime)
    return _wait(ctx, token, data["publish_id"], mode)

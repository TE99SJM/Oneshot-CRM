"""Upload a video to YouTube with the resumable upload protocol (videos.insert)."""
import re

from ..integrations import youtube as yt
from ..integrations.base import SyncContext, SyncError, check_response
from .common import UPLOAD_TIMEOUT, PublishInput, PublishResult, clip, file_path, read_range

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 32 * 1024 * 1024          # multiple of 256 KiB as YouTube requires
PRIVACY = {"public", "unlisted", "private"}


def title_for(item: PublishInput) -> str:
    t = item.options.get("title") or item.title or (item.text.strip().split("\n")[0] if item.text.strip() else "")
    return clip(re.sub(r"[<>]", "", t), 100)


def validate(item: PublishInput) -> list[str]:
    errs = []
    if len(item.videos) != 1 or item.images:
        errs.append("YouTube needs exactly one video (and no photos).")
    if not title_for(item):
        errs.append("YouTube needs a title.")
    if item.options.get("privacy", "public") not in PRIVACY:
        errs.append("YouTube privacy must be public, unlisted or private.")
    return errs


def publish(ctx: SyncContext, item: PublishInput) -> PublishResult:
    token = yt.access_token(ctx.client, ctx.config, ctx.secrets)
    m = item.videos[0]
    path = file_path(m)
    size = path.stat().st_size
    tags = [t.strip() for t in str(item.options.get("tags") or "").split(",") if t.strip()]
    body = {
        "snippet": {"title": title_for(item), "description": clip(re.sub(r"[<>]", "", item.text_with_link()), 5000),
                    "categoryId": str(item.options.get("category_id") or "22")},
        "status": {"privacyStatus": item.options.get("privacy") or "public",
                   "selfDeclaredMadeForKids": bool(item.options.get("made_for_kids", False))},
    }
    if tags:
        body["snippet"]["tags"] = tags[:30]
    auth = {"Authorization": f"Bearer {token}"}
    init = ctx.client.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status",
                                               "notifySubscribers": "true" if item.options.get("notify", True) else "false"},
                           json=body, headers={**auth, "X-Upload-Content-Length": str(size),
                                               "X-Upload-Content-Type": m.mime or "video/mp4"})
    if init.status_code >= 400:
        check_response(init, "YouTube")
    session = init.headers.get("location")
    if not session:
        raise SyncError("YouTube: the upload session didn't start (no upload address returned)")

    start = 0
    video = None
    while start < size:
        end = min(start + CHUNK, size)
        resp = ctx.client.put(session, content=read_range(path, start, end), timeout=UPLOAD_TIMEOUT,
                              headers={**auth, "Content-Range": f"bytes {start}-{end - 1}/{size}",
                                       "Content-Type": m.mime or "video/mp4"})
        if resp.status_code == 308:
            rng = resp.headers.get("range", "")
            start = int(rng.rsplit("-", 1)[-1]) + 1 if rng else start
            continue
        video = check_response(resp, "YouTube")
        break
    if not video or not video.get("id"):
        raise SyncError("YouTube: the upload finished without a video ID. Check YouTube Studio before retrying.")
    vid = video["id"]
    note = ""
    if (video.get("status") or {}).get("uploadStatus") == "rejected":
        note = f"YouTube rejected the video: {(video.get('status') or {}).get('rejectionReason', 'unknown reason')}"
    return PublishResult(vid, f"https://www.youtube.com/watch?v={vid}", status="processing",
                         note=note or "YouTube is processing the video; it can take a few minutes to go live.")

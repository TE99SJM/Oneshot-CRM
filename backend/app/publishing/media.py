"""Store uploaded photos/videos on disk and expose them for platforms that fetch by URL."""
import mimetypes
import secrets
import shutil
from pathlib import Path

from fastapi import UploadFile

from ..config import settings
from ..models import MediaFile

MEDIA_DIR = settings.data_dir / "media"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


def media_dir() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def path_of(m: MediaFile) -> Path:
    return media_dir() / m.stored_name


def jpeg_path_of(m: MediaFile) -> Path:
    return media_dir() / (m.jpeg_name or m.stored_name)


def classify(filename: str, content_type: str | None) -> tuple[str, str]:
    ext = Path(filename or "").suffix.lower()
    mime = (content_type or "").lower()
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(filename or "")[0] or ""
    if mime.startswith("image/") or ext in IMAGE_EXT:
        return "image", mime or "image/jpeg"
    if mime.startswith("video/") or ext in VIDEO_EXT:
        return "video", mime or "video/mp4"
    raise ValueError("Only photos and videos can be attached")


def save_upload(upload: UploadFile) -> MediaFile:
    kind, mime = classify(upload.filename or "", upload.content_type)
    token = secrets.token_urlsafe(24)
    ext = Path(upload.filename or "").suffix.lower() or (".jpg" if kind == "image" else ".mp4")
    stored = f"{token}{ext}"
    dest = media_dir() / stored
    with dest.open("wb") as out:
        shutil.copyfileobj(upload.file, out, length=1024 * 1024)
    m = MediaFile(token=token, filename=(upload.filename or stored)[:255], stored_name=stored, mime=mime, kind=kind,
                  size=dest.stat().st_size)
    if kind == "image":
        _prepare_image(m, dest)
    return m


def _prepare_image(m: MediaFile, src: Path) -> None:
    """Read the size and make a JPEG copy when needed (Instagram only accepts JPEG)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:          # Pillow missing: keep the original, Instagram may reject non-JPEG
        return
    try:
        with Image.open(src) as im:
            m.width, m.height = im.size
            if (im.format or "").upper() == "JPEG" and im.mode in ("RGB", "L"):
                return
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            m.jpeg_name = f"{m.token}.ig.jpg"
            im.save(media_dir() / m.jpeg_name, "JPEG", quality=92)
    except Exception:            # unreadable/unsupported image (e.g. HEIC without a plugin): keep as is
        return


def delete_files(m: MediaFile) -> None:
    for name in {m.stored_name, m.jpeg_name}:
        if name:
            (media_dir() / name).unlink(missing_ok=True)

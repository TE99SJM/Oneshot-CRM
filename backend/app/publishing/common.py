"""Shared types and helpers for the platform publishers."""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import httpx

from ..integrations.base import SyncError, check_response
from ..models import MediaFile
from . import media as media_store

UPLOAD_TIMEOUT = httpx.Timeout(900, connect=30)   # big chunks over slow home upload links
sleep = time.sleep                                 # patched in tests


@dataclass
class PublishInput:
    title: str
    text: str
    link: str
    media: list[MediaFile]
    options: dict = field(default_factory=dict)
    public_base: str = ""                          # e.g. https://mserver.tailnet.ts.net (optional)

    @property
    def images(self) -> list[MediaFile]:
        return [m for m in self.media if m.kind == "image"]

    @property
    def videos(self) -> list[MediaFile]:
        return [m for m in self.media if m.kind == "video"]

    def text_with_link(self) -> str:
        if self.link and self.link not in self.text:
            return f"{self.text}\n\n{self.link}".strip()
        return self.text

    def public_url(self, m: MediaFile) -> str:
        if not self.public_base:
            return ""
        ext = ".jpg" if m.kind == "image" else (Path(m.stored_name).suffix or ".mp4")
        return f"{self.public_base.rstrip('/')}/api/media/public/{m.token}{ext}"


@dataclass
class PublishResult:
    external_id: str
    url: str = ""
    status: str = "posted"                         # posted|processing
    note: str = ""


def checked(resp: httpx.Response, platform: str, hint: str = "") -> dict:
    try:
        return check_response(resp, platform)
    except SyncError as e:
        msg = str(e)
        if hint and resp.status_code in (400, 401, 403) and any(
                w in msg.lower() for w in ("permission", "scope", "access denied", "(#200)", "(#10)", "credentials", "insufficient")):
            msg += f". {hint}"
        raise SyncError(msg) from None


def file_chunks(path: Path, start: int = 0, end: int | None = None, size: int = 4 * 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as f:
        f.seek(start)
        remaining = (end if end is not None else path.stat().st_size) - start
        while remaining > 0:
            data = f.read(min(size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def read_range(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as f:
        f.seek(start)
        return f.read(end - start)


def file_path(m: MediaFile) -> Path:
    p = media_store.path_of(m)
    if not p.exists():
        raise SyncError(f"The file “{m.filename}” is no longer on the server (media is cleared 14 days after posting). "
                        "Attach it again in a new post.")
    return p


def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"

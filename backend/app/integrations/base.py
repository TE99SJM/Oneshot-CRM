"""Shared provider interface, HTTP client factory and upsert helpers."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Channel, Contact, Deal, Post

USER_AGENT = "OneshotCRM/1.1 (+self-hosted)"


class SyncError(Exception):
    """A user-facing error (bad credentials, missing permission, platform outage)."""


def make_client() -> httpx.Client:
    """Factory so tests can swap in a mock transport."""
    return httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@dataclass
class FieldSpec:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""
    help: str = ""
    kind: str = "text"            # text|select|json_file
    options: list[str] = field(default_factory=list)
    default: str = ""


FAST_INTERVAL = 15   # sales + messages sync every 15 minutes by default


@dataclass
class ProviderInfo:
    key: str
    name: str
    platform: str                 # Channel.platform value
    channel_kind: str             # Channel.kind value
    summary: str
    syncs: list[str]
    fields: list[FieldSpec]
    steps: list[str]
    docs_url: str
    default_interval: int = 360   # minutes between automatic syncs (stats: 6 h; sales/messages are faster)


@dataclass
class SyncContext:
    db: Session
    client: httpx.Client
    channel: Channel
    config: dict
    secrets: dict
    last_sync_at: datetime | None
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    integration_id: int | None = None
    metrics: dict = field(default_factory=dict)      # key -> {value, label, unit, section, window, combine}

    def metric(self, key: str, value, label: str | None = None, unit: str | None = None, section: str | None = None,
               window: str = "now", combine: str | None = None) -> None:
        """Record one number from the platform's API. Unknown/None values are skipped."""
        if value is None or value == "":
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        self.metrics[key] = {"value": v, "label": label, "unit": unit, "section": section, "window": window,
                             "combine": combine}

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n


Provider = Callable[[SyncContext], None]


def parse_dt(value: str | None) -> datetime | None:
    """Parse ISO-8601 (with Z or offset) into naive UTC."""
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    if len(v) >= 5 and v[-5] in "+-" and v[-3] != ":":       # +0000 -> +00:00 (Facebook style)
        v = f"{v[:-2]}:{v[-2:]}"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def check_response(resp: httpx.Response, platform: str) -> Any:
    """Raise a readable SyncError for HTTP errors, otherwise return parsed JSON."""
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                detail = err.get("message") or ""
            elif isinstance(body, dict) and body.get("errors"):
                detail = "; ".join(e.get("detail", "") for e in body["errors"] if isinstance(e, dict))
        except ValueError:
            detail = resp.text[:200]
        hint = {401: "credentials were rejected", 403: "access denied (check permissions)", 404: "not found",
                429: "rate limited, try again later"}.get(resp.status_code, f"HTTP {resp.status_code}")
        raise SyncError(f"{platform}: {hint}{' - ' + detail if detail else ''}")
    try:
        return resp.json()
    except ValueError as e:
        raise SyncError(f"{platform}: unexpected non-JSON response") from e


def upsert_post(ctx: SyncContext, source: str, external_id: str, *, title: str, body: str = "", url: str = "",
                published_at: datetime | None, views: int = 0, likes: int = 0, comments: int = 0,
                shares: int = 0, clicks: int | None = None) -> Post:
    post = ctx.db.scalar(select(Post).where(Post.external_source == source, Post.external_id == external_id))
    if post is None:
        post = Post(external_source=source, external_id=external_id, channel_id=ctx.channel.id,
                    title=(title or "(untitled)")[:200], body=body, status="published",
                    published_at=published_at, scheduled_at=published_at, url=url)
        ctx.db.add(post)
        ctx.count("posts_created")
    else:
        ctx.count("posts_updated")
        post.url = url or post.url
        post.published_at = published_at or post.published_at
    post.views, post.likes, post.comments, post.shares = int(views or 0), int(likes or 0), int(comments or 0), int(shares or 0)
    if clicks is not None:
        post.clicks = int(clicks)
    return post


def find_external(db: Session, model: type[Contact] | type[Deal], source: str, external_id: str):
    return db.scalar(select(model).where(model.external_source == source, model.external_id == external_id))

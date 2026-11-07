"""Run publish jobs (now or when scheduled), record results, and tidy up old media."""
import json
import logging
import threading
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import select

from ..database import SessionLocal
from ..integrations import base
from ..integrations.service import _context
from ..models import Integration, MediaFile, Post, PublishJob, PublishTarget, utcnow
from . import facebook, instagram, media as media_store, youtube
from .common import PublishInput

log = logging.getLogger("oneshot.publish")
PUBLISHERS = {"facebook": facebook, "instagram": instagram, "youtube": youtube}
FINAL = {"done", "partial", "failed", "canceled"}
KEEP_MEDIA = timedelta(days=14)
_running: set[int] = set()
_guard = threading.Lock()


# ---------------------------------------------------------------- readiness / helpers
def readiness(integ: Integration, secrets: dict) -> tuple[bool, str]:
    if integ.provider == "youtube":
        if not secrets.get("refresh_token"):
            return False, "Posting not set up yet: Integrations → YouTube → “Set up posting”."
        return True, ""
    if not secrets.get("page_token"):
        return False, "No Page token saved."
    return True, ""


def public_base(db, integ: Integration | None) -> str:
    """Public https address that serves /api/media/public (optional). From the Instagram connection,
    otherwise borrowed from the eBay account-deletion endpoint (same Tailscale Funnel host)."""
    if integ is not None:
        v = (json.loads(integ.config or "{}").get("public_base_url") or "").strip()
        if v:
            u = urlparse(v if "://" in v else f"https://{v}")
            return f"{u.scheme}://{u.netloc}"
    for e in db.scalars(select(Integration).where(Integration.provider == "ebay")).all():
        ep = (json.loads(e.config or "{}").get("deletion_endpoint") or "").strip()
        if ep.startswith("https://"):
            u = urlparse(ep)
            return f"{u.scheme}://{u.netloc}"
    return ""


def job_media(db, job: PublishJob) -> list[MediaFile]:
    ids = json.loads(job.media_ids or "[]")
    rows = {m.id: m for m in db.scalars(select(MediaFile).where(MediaFile.id.in_(ids))).all()} if ids else {}
    return [rows[i] for i in ids if i in rows]


def make_input(db, job: PublishJob, target: PublishTarget, integ: Integration | None) -> PublishInput:
    return PublishInput(title=job.title, text=job.text, link=job.link, media=job_media(db, job),
                        options=json.loads(target.options or "{}"),
                        public_base=public_base(db, integ) if target.platform == "instagram" else "")


def post_title(job: PublishJob) -> str:
    first = job.text.strip().split("\n")[0] if job.text.strip() else ""
    return (job.title or first or job.link or "Post")[:200]


# ---------------------------------------------------------------- running
def _finish_job(job: PublishJob) -> None:
    states = [t.status for t in job.targets if t.status != "canceled"]
    if any(s in ("pending", "posting") for s in states):
        return
    ok = [s for s in states if s in ("posted", "processing")]
    job.status = "done" if states and len(ok) == len(states) else ("failed" if not ok else "partial")
    job.finished_at = utcnow()


def run_job(job_id: int) -> None:
    with _guard:
        if job_id in _running:
            return
        _running.add(job_id)
    try:
        with SessionLocal() as db:
            job = db.get(PublishJob, job_id)
            if job is None or job.status == "canceled":
                return
            job.status = "posting"
            db.commit()
            for t in list(job.targets):
                if t.status != "pending":
                    continue
                _run_target(db, job, t)
            _finish_job(job)
            db.commit()
    finally:
        with _guard:
            _running.discard(job_id)


def _run_target(db, job: PublishJob, t: PublishTarget) -> None:
    t.status, t.attempts, t.error = "posting", t.attempts + 1, ""
    db.commit()
    integ = db.get(Integration, t.integration_id) if t.integration_id else None
    try:
        if integ is None:
            raise base.SyncError("This connection was removed from Integrations")
        with base.make_client() as client:
            ctx = _context(db, integ, client)
            result = PUBLISHERS[t.platform].publish(ctx, make_input(db, job, t, integ))
        t.status, t.external_id, t.url, t.posted_at = result.status, result.external_id, result.url, utcnow()
        t.error = result.note
        post = db.get(Post, t.post_id) if t.post_id else None
        dup = db.scalar(select(Post).where(Post.external_source == t.platform, Post.external_id == result.external_id))
        if dup is not None and post is not None and dup.id != post.id:
            db.delete(post)                     # a sync already picked it up; keep that one
            post = dup
        if post is None:
            post = dup or Post(title=post_title(job), body=job.text, channel_id=integ.channel_id)
            db.add(post)
        post.status, post.published_at, post.url = "published", t.posted_at, result.url or post.url
        post.external_source, post.external_id = t.platform, result.external_id
        post.channel_id = post.channel_id or integ.channel_id
        db.flush()
        t.post_id = post.id
    except Exception as e:  # noqa: BLE001 - record any failure on the target
        db.rollback()
        t = db.get(PublishTarget, t.id)
        t.status = "failed"
        t.error = str(e) if isinstance(e, (base.SyncError, ValueError)) else f"{type(e).__name__}: {e}"
        log.warning("publish %s target %s failed: %s", t.platform, t.id, t.error)
    db.commit()


def start(job_id: int) -> None:
    threading.Thread(target=run_job, args=(job_id,), daemon=True, name=f"publish-{job_id}").start()


def run_due() -> None:
    """Called every minute by the scheduler: start scheduled jobs whose time has come."""
    with SessionLocal() as db:
        due = db.scalars(select(PublishJob.id).where(PublishJob.status == "scheduled",
                                                     PublishJob.scheduled_at <= utcnow())).all()
    for job_id in due:
        start(job_id)
    cleanup_media()


def reset_interrupted() -> None:
    """After a restart, anything left 'posting' may or may not have gone out."""
    with SessionLocal() as db:
        for t in db.scalars(select(PublishTarget).where(PublishTarget.status == "posting")).all():
            t.status = "failed"
            t.error = ("Interrupted by a restart while posting. Check the platform first so it isn't posted twice, "
                       "then click Retry if needed.")
        for job in db.scalars(select(PublishJob).where(PublishJob.status == "posting")).all():
            for t in job.targets:
                if t.status == "pending":
                    t.status = "failed"
                    t.error = "Interrupted by a restart before posting. Click Retry."
            _finish_job(job)
        db.commit()


_last_cleanup = [None]


def cleanup_media(force: bool = False) -> int:
    """Delete media files 14 days after a post finished, and unattached uploads after 2 days."""
    now = utcnow()
    if not force and _last_cleanup[0] and _last_cleanup[0] + timedelta(hours=6) > now:
        return 0
    _last_cleanup[0] = now
    removed = 0
    with SessionLocal() as db:
        jobs = db.scalars(select(PublishJob)).all()
        in_use: set[int] = set()
        for j in jobs:
            ids = set(json.loads(j.media_ids or "[]"))
            old = j.status in FINAL and (j.finished_at or j.created_at) + KEEP_MEDIA < now
            if old and not j.media_deleted:
                j.media_deleted = True
            if not old:
                in_use |= ids
        referenced = {i for j in jobs for i in json.loads(j.media_ids or "[]")}
        for m in db.scalars(select(MediaFile)).all():
            if m.id in in_use:
                continue
            if m.id in referenced or m.created_at + timedelta(days=2) < now:
                media_store.delete_files(m)
                db.delete(m)
                removed += 1
        db.commit()
    return removed

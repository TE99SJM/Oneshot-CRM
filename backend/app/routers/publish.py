"""Compose & publish API: upload media, create posts for Facebook/Instagram/YouTube, schedule, retry."""
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..integrations.base import parse_dt
from ..integrations.crypto import decrypt_secrets
from ..models import Integration, MediaFile, Post, PublishJob, PublishTarget, utcnow
from ..publishing import media as media_store, runner
from ..publishing.common import PublishInput

router = APIRouter(prefix="/api/publish", tags=["publish"], dependencies=[Depends(current_user)])
public_router = APIRouter(tags=["publish"])          # no auth: platforms fetch media from here

POSTING_PROVIDERS = ("facebook", "instagram", "youtube")


class TargetIn(BaseModel):
    integration_id: int
    options: dict = {}


class JobIn(BaseModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=63000)
    link: str = Field(default="", max_length=1000)
    media_ids: list[int] = []
    targets: list[TargetIn] = Field(min_length=1)
    scheduled_at: str | None = None            # ISO time; empty = post now


class JobPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=63000)
    link: str | None = Field(default=None, max_length=1000)
    scheduled_at: str | None = None


def _media_out(m: MediaFile) -> dict:
    ext = ".jpg" if m.kind == "image" and m.jpeg_name else (m.stored_name[m.stored_name.rfind("."):] if "." in m.stored_name else "")
    return {"id": m.id, "filename": m.filename, "kind": m.kind, "mime": m.mime, "size": m.size, "width": m.width,
            "height": m.height, "url": f"/api/media/public/{m.token}{ext}"}


def _job_out(db: Session, job: PublishJob) -> dict:
    return {
        "id": job.id, "title": job.title, "text": job.text, "link": job.link, "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "created_at": job.created_at.isoformat(), "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "media_deleted": job.media_deleted,
        "media": [] if job.media_deleted else [_media_out(m) for m in runner.job_media(db, job)],
        "targets": [{"id": t.id, "platform": t.platform, "name": t.name, "integration_id": t.integration_id,
                     "options": json.loads(t.options or "{}"), "status": t.status, "url": t.url,
                     "external_id": t.external_id, "error": t.error, "attempts": t.attempts, "post_id": t.post_id,
                     "posted_at": t.posted_at.isoformat() if t.posted_at else None} for t in job.targets],
    }


def _parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = parse_dt(value)
    if dt is None:
        raise HTTPException(422, "Couldn't read the scheduled time")
    return dt


# ---------------------------------------------------------------- targets & media
@router.get("/targets")
def targets(db: Session = Depends(get_db)):
    out = []
    for i in db.scalars(select(Integration).where(Integration.provider.in_(POSTING_PROVIDERS)).order_by(Integration.id)).all():
        try:
            secrets = decrypt_secrets(i.secrets)
        except ValueError:
            secrets = {}
        ready, note = runner.readiness(i, secrets)
        cfg = json.loads(i.config or "{}")
        out.append({"integration_id": i.id, "platform": i.provider, "name": i.name, "enabled": i.enabled,
                    "channel_id": i.channel_id, "channel_name": i.channel.name if i.channel else None,
                    "ready": ready, "note": note,
                    "account": cfg.get("upload_channel_title", "") if i.provider == "youtube" else "",
                    "public_media": bool(runner.public_base(db, i)) if i.provider == "instagram" else None})
    return out


@router.post("/media", status_code=201)
def upload_media(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    saved = []
    for f in files:
        try:
            m = media_store.save_upload(f)
        except ValueError as e:
            raise HTTPException(422, f"{f.filename}: {e}") from e
        db.add(m)
        saved.append(m)
    db.commit()
    return [_media_out(m) for m in saved]


@router.delete("/media/{media_id}", status_code=204)
def delete_media(media_id: int, db: Session = Depends(get_db)):
    m = get_or_404(db, MediaFile, media_id)
    for j in db.scalars(select(PublishJob).where(PublishJob.status.in_(("scheduled", "posting")))).all():
        if media_id in json.loads(j.media_ids or "[]"):
            raise HTTPException(409, "That file is attached to a scheduled post")
    media_store.delete_files(m)
    db.delete(m)
    db.commit()


# ---------------------------------------------------------------- jobs
@router.post("", status_code=201)
def create_job(data: JobIn, db: Session = Depends(get_db)):
    media = [get_or_404(db, MediaFile, mid) for mid in data.media_ids]
    when = _parse_when(data.scheduled_at)
    if when and when < utcnow().replace(second=0, microsecond=0):
        raise HTTPException(422, "The scheduled time is in the past")
    job = PublishJob(title=data.title.strip(), text=data.text.strip(), link=data.link.strip(),
                     media_ids=json.dumps([m.id for m in media]), scheduled_at=when,
                     status="scheduled" if when else "posting")
    errors, seen = [], set()
    for t in data.targets:
        integ = get_or_404(db, Integration, t.integration_id)
        if integ.provider not in POSTING_PROVIDERS:
            raise HTTPException(422, f"{integ.name} can't be posted to")
        if integ.id in seen:
            continue
        seen.add(integ.id)
        try:
            ready, note = runner.readiness(integ, decrypt_secrets(integ.secrets))
        except ValueError:
            ready, note = False, "Saved credentials can't be read; re-enter them in Integrations."
        if not ready:
            errors.append(f"{integ.name}: {note}")
        opts = {k: v for k, v in t.options.items() if isinstance(v, (str, bool, int, float))}
        item = PublishInput(title=job.title, text=job.text, link=job.link, media=media, options=opts)
        errors += [f"{integ.name}: {e}" for e in runner.PUBLISHERS[integ.provider].validate(item)]
        post = Post(title=runner.post_title(job), body=job.text, status="scheduled", channel_id=integ.channel_id,
                    scheduled_at=when or utcnow())
        db.add(post)
        db.flush()
        job.targets.append(PublishTarget(integration_id=integ.id, platform=integ.provider, name=integ.name,
                                         options=json.dumps(opts), post_id=post.id))
    if errors:
        db.rollback()
        raise HTTPException(422, " ".join(errors))
    db.add(job)
    db.commit()
    if not when:
        runner.start(job.id)
    return _job_out(db, job)


@router.get("")
def list_jobs(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = select(PublishJob).order_by(PublishJob.id.desc()).limit(max(1, min(limit, 500)))
    if status == "scheduled":
        q = q.where(PublishJob.status == "scheduled")
    elif status:
        q = q.where(PublishJob.status == status)
    return [_job_out(db, j) for j in db.scalars(q).all()]


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    return _job_out(db, get_or_404(db, PublishJob, job_id))


@router.patch("/{job_id}")
def update_job(job_id: int, data: JobPatch, db: Session = Depends(get_db)):
    job = get_or_404(db, PublishJob, job_id)
    if job.status != "scheduled":
        raise HTTPException(409, "Only scheduled posts can be changed")
    patch = data.model_dump(exclude_unset=True)
    for k in ("title", "text", "link"):
        if patch.get(k) is not None:
            setattr(job, k, patch[k].strip())
    if "scheduled_at" in patch:
        when = _parse_when(patch["scheduled_at"])
        if not when:
            raise HTTPException(422, "Pick a time, or use Post now")
        job.scheduled_at = when
    for t in job.targets:
        post = db.get(Post, t.post_id) if t.post_id else None
        if post and post.status == "scheduled":
            post.title, post.body, post.scheduled_at = runner.post_title(job), job.text, job.scheduled_at
    db.commit()
    return _job_out(db, job)


@router.post("/{job_id}/post-now")
def post_now(job_id: int, db: Session = Depends(get_db)):
    job = get_or_404(db, PublishJob, job_id)
    if job.status != "scheduled":
        raise HTTPException(409, "This post isn't waiting to be scheduled")
    job.status, job.scheduled_at = "posting", utcnow()
    db.commit()
    runner.start(job.id)
    return _job_out(db, job)


@router.post("/{job_id}/retry")
def retry(job_id: int, db: Session = Depends(get_db)):
    job = get_or_404(db, PublishJob, job_id)
    failed = [t for t in job.targets if t.status == "failed"]
    if not failed or job.status in ("posting", "scheduled"):
        raise HTTPException(409, "Nothing to retry")
    if job.media_deleted:
        raise HTTPException(409, "The media for this post has been cleared. Create a new post instead.")
    for t in failed:
        t.status = "pending"
    job.status, job.finished_at = "posting", None
    db.commit()
    runner.start(job.id)
    return _job_out(db, job)


@router.post("/{job_id}/cancel")
def cancel(job_id: int, db: Session = Depends(get_db)):
    job = get_or_404(db, PublishJob, job_id)
    if job.status != "scheduled":
        raise HTTPException(409, "Only scheduled posts can be canceled")
    job.status, job.finished_at = "canceled", utcnow()
    for t in job.targets:
        t.status = "canceled"
        post = db.get(Post, t.post_id) if t.post_id else None
        if post and post.status == "scheduled":
            db.delete(post)
            t.post_id = None
    db.commit()
    return _job_out(db, job)


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    """Remove from the history. Posts already on Facebook/Instagram/YouTube are not touched."""
    job = get_or_404(db, PublishJob, job_id)
    if job.status == "posting":
        raise HTTPException(409, "Wait for posting to finish")
    for t in job.targets:
        post = db.get(Post, t.post_id) if t.post_id else None
        if post and post.status == "scheduled":
            db.delete(post)
    db.delete(job)
    db.commit()


# ---------------------------------------------------------------- public media (for Instagram's fetcher)
_NAME = re.compile(r"^([A-Za-z0-9_-]{20,64})(\.[A-Za-z0-9]{2,5})?$")


@public_router.get("/api/media/public/{rest:path}", include_in_schema=False)
def public_media(rest: str, db: Session = Depends(get_db)):
    name = rest.rstrip("/").rsplit("/", 1)[-1]          # tolerate proxies that repeat the path prefix
    match = _NAME.match(name)
    if not match:
        raise HTTPException(404, "Not found")
    m = db.scalar(select(MediaFile).where(MediaFile.token == match.group(1)))
    if m is None:
        raise HTTPException(404, "Not found")
    if m.kind == "image" and m.jpeg_name:
        path, mime = media_store.jpeg_path_of(m), "image/jpeg"
    else:
        path, mime = media_store.path_of(m), m.mime
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})

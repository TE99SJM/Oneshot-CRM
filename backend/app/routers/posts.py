from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, ensure_exists, get_or_404
from ..models import Channel, Post, utcnow
from ..schemas import PostIn, PostOut, PostPatch

router = APIRouter(prefix="/api/posts", tags=["posts"], dependencies=[Depends(current_user)])


def _normalize(post: Post) -> None:
    if post.status == "published" and post.published_at is None:
        post.published_at = post.scheduled_at or utcnow()


@router.get("", response_model=list[PostOut])
def list_posts(channel_id: int | None = None, status: str | None = None,
               start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db)):
    """List posts. ``start``/``end`` filter on scheduled_at (or published_at) for calendar views."""
    stmt = select(Post)
    if channel_id:
        stmt = stmt.where(Post.channel_id == channel_id)
    if status:
        stmt = stmt.where(Post.status == status)
    if start:
        stmt = stmt.where((Post.scheduled_at >= start) | (Post.published_at >= start))
    if end:
        stmt = stmt.where((Post.scheduled_at < end) | (Post.published_at < end))
    return db.scalars(stmt.order_by(Post.scheduled_at.is_(None), Post.scheduled_at, Post.id.desc())).all()


@router.post("", response_model=PostOut, status_code=201)
def create_post(data: PostIn, db: Session = Depends(get_db)):
    ensure_exists(db, Channel, data.channel_id, "Channel")
    post = Post(**data.model_dump())
    _normalize(post)
    db.add(post)
    db.commit()
    return post


@router.get("/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Post, post_id)


@router.patch("/{post_id}", response_model=PostOut)
def update_post(post_id: int, data: PostPatch, db: Session = Depends(get_db)):
    post = get_or_404(db, Post, post_id)
    changes = data.model_dump(exclude_unset=True)
    if "channel_id" in changes:
        ensure_exists(db, Channel, changes["channel_id"], "Channel")
    for k, v in changes.items():
        setattr(post, k, v)
    _normalize(post)
    db.commit()
    return post


@router.delete("/{post_id}", status_code=204)
def delete_post(post_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Post, post_id))
    db.commit()

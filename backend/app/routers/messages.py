"""Messages inbox: TikTok Shop buyer chats (pulled on every sync), with replies sent back to the platform."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..integrations import base
from ..integrations.base import SyncError
from ..integrations.messages_store import refresh_summary, upsert_message
from ..integrations.service import _context
from ..models import Conversation, Integration, Message, utcnow

router = APIRouter(prefix="/api/messages", tags=["messages"], dependencies=[Depends(current_user)])

SENDERS = {"tiktok_shop": "send_message"}      # provider module function that sends a reply


def _conv_out(c: Conversation) -> dict:
    return {"id": c.id, "source": c.source, "integration_id": c.integration_id, "external_id": c.external_id,
            "contact_id": c.contact_id, "title": c.title, "avatar_url": c.avatar_url, "last_message": c.last_message,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None, "unread": c.unread,
            "can_reply": c.can_reply, "reply_note": c.reply_note}


def _msg_out(m: Message) -> dict:
    return {"id": m.id, "direction": m.direction, "sender_name": m.sender_name, "kind": m.kind, "body": m.body,
            "sent_at": m.sent_at.isoformat() if m.sent_at else None}


@router.get("")
def list_conversations(source: str | None = None, q: str = "", unread_only: bool = False, limit: int = 200,
                       db: Session = Depends(get_db)):
    stmt = select(Conversation)
    if source:
        stmt = stmt.where(Conversation.source == source)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Conversation.title.ilike(like) | Conversation.last_message.ilike(like))
    if unread_only:
        stmt = stmt.where(Conversation.unread > 0)
    stmt = stmt.order_by(Conversation.last_message_at.desc().nullslast()).limit(max(1, min(limit, 1000)))
    rows = db.scalars(stmt).all()
    unread = db.scalar(select(func.coalesce(func.sum(Conversation.unread), 0))) or 0
    return {"conversations": [_conv_out(c) for c in rows], "unread_total": int(unread)}


def _status_row(db: Session, integ: Integration) -> dict:
    from ..integrations import tiktok_shop
    from ..integrations.crypto import decrypt_secrets
    cfg = json.loads(integ.config or "{}")
    try:
        sec = decrypt_secrets(integ.secrets)
    except ValueError:
        sec = {}
    signed_in = bool(sec.get("refresh_token") or sec.get("access_token"))
    status = cfg.get("messages_status") or ("unknown" if signed_in else "not_signed_in")
    if not signed_in:
        status = "not_signed_in"
    return {"integration_id": integ.id, "name": integ.name, "source": "tiktok_shop", "enabled": integ.enabled,
            "signed_in": signed_in, "status": status, "error": cfg.get("messages_error", ""),
            "checked_at": cfg.get("messages_checked_at"), "activated_at": cfg.get("messages_activated_at"),
            "every_minutes": tiktok_shop.messages_every(cfg),
            "recheck_minutes": tiktok_shop.WAITING_RECHECK_MINUTES if status == "waiting_approval" else None}


@router.get("/status")
def messages_status(db: Session = Depends(get_db)):
    """Whether buyer chats work for each TikTok Shop connection (waiting for approval, active, error…)."""
    rows = db.scalars(select(Integration).where(Integration.provider == "tiktok_shop").order_by(Integration.id)).all()
    return [_status_row(db, i) for i in rows]


@router.post("/check")
def check_now(db: Session = Depends(get_db)):
    """Check every TikTok Shop connection for new buyer messages right now."""
    from ..integrations import tiktok_shop
    out = []
    for integ in db.scalars(select(Integration).where(Integration.provider == "tiktok_shop").order_by(Integration.id)).all():
        result = tiktok_shop.check_messages(db, integ)
        db.expire_all()
        out.append({**_status_row(db, db.get(Integration, integ.id)), "result": result})
    return out


@router.get("/{conv_id}")
def get_conversation(conv_id: int, db: Session = Depends(get_db)):
    c = get_or_404(db, Conversation, conv_id)
    return {**_conv_out(c), "messages": [_msg_out(m) for m in c.messages]}


def _provider(db: Session, c: Conversation):
    from ..integrations.registry import PROVIDERS
    integ = db.get(Integration, c.integration_id) if c.integration_id else None
    if integ is None:
        raise HTTPException(409, "The connection for this chat was removed from Integrations")
    return integ, PROVIDERS[integ.provider]


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/{conv_id}/reply")
def reply(conv_id: int, data: ReplyIn, db: Session = Depends(get_db)):
    c = get_or_404(db, Conversation, conv_id)
    if not c.can_reply:
        raise HTTPException(409, c.reply_note or "Replies are closed for this chat")
    integ, mod = _provider(db, c)
    try:
        with base.make_client() as client:
            ctx = _context(db, integ, client)
            ext_id = getattr(mod, SENDERS[c.source])(ctx, c, data.text.strip())
    except SyncError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    c = db.get(Conversation, conv_id)
    ctx.db = db
    m = upsert_message(ctx, c, ext_id, direction="out", body=data.text.strip(), sent_at=utcnow(),
                       sender_name=json.loads(integ.config or "{}").get("shop_name") or "You")
    c.unread = 0
    db.flush()
    db.refresh(c)
    refresh_summary(c)
    db.commit()
    return _msg_out(m)


@router.post("/{conv_id}/refresh")
def refresh(conv_id: int, db: Session = Depends(get_db)):
    """Pull this chat's full recent history from the platform."""
    c = get_or_404(db, Conversation, conv_id)
    integ, mod = _provider(db, c)
    try:
        with base.make_client() as client:
            ctx = _context(db, integ, client)
            mod.load_older(ctx, c)
    except SyncError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    db.flush()
    db.refresh(c)
    refresh_summary(c)
    db.commit()
    return get_conversation(conv_id, db)


@router.post("/{conv_id}/read")
def mark_read(conv_id: int, db: Session = Depends(get_db)):
    c = get_or_404(db, Conversation, conv_id)
    c.unread = 0
    db.commit()
    return _conv_out(c)

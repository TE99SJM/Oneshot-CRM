"""Save conversations and messages pulled from platforms into the Messages inbox."""
import json
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import Conversation, Message
from .base import SyncContext


def from_ts(v) -> datetime | None:
    """Unix seconds or milliseconds -> naive UTC datetime."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n > 1e12:
        n /= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc).replace(tzinfo=None)


def upsert_conversation(ctx: SyncContext, source: str, external_id: str, **fields) -> Conversation:
    conv = ctx.db.scalar(select(Conversation).where(Conversation.source == source,
                                                    Conversation.external_id == external_id,
                                                    Conversation.integration_id == ctx.integration_id))
    if conv is None:
        conv = Conversation(source=source, external_id=external_id, integration_id=ctx.integration_id)
        ctx.db.add(conv)
        ctx.count("conversations_created")
    for k, v in fields.items():
        if v is None:
            continue
        if k == "extra":
            v = json.dumps(v)
        setattr(conv, k, v)
    ctx.db.flush()
    return conv


def upsert_message(ctx: SyncContext, conv: Conversation, external_id: str, *, direction: str, body: str,
                   sent_at: datetime | None, sender_name: str = "", kind: str = "TEXT", raw: dict | None = None) -> Message:
    msg = None
    if external_id:
        msg = ctx.db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.external_id == external_id))
    if msg is None:
        msg = Message(conversation_id=conv.id, external_id=external_id)
        ctx.db.add(msg)
        ctx.count("messages_synced")
    msg.direction, msg.body, msg.sent_at = direction, body or "", sent_at
    msg.sender_name, msg.kind = sender_name[:200], kind[:30]
    msg.raw = json.dumps(raw or {})
    return msg


def refresh_summary(conv: Conversation) -> None:
    msgs = [m for m in conv.messages if m.sent_at]
    if msgs:
        last = max(msgs, key=lambda m: m.sent_at)
        if not conv.last_message_at or last.sent_at >= conv.last_message_at:
            conv.last_message_at = last.sent_at
            conv.last_message = (last.body or f"[{last.kind.lower()}]")[:300]

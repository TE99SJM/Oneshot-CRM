"""Emails pulled from Gmail, linked to contacts."""
import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..models import Contact, Email

router = APIRouter(prefix="/api/emails", tags=["emails"], dependencies=[Depends(current_user)])

LIST_FIELDS = ["id", "account", "gm_msgid", "thread_id", "direction", "from_name", "from_email", "to_addrs", "cc_addrs",
               "subject", "snippet", "labels", "unread", "bulk", "contact_id"]


def _row(e: Email, contacts: dict[int, Contact] | None = None) -> dict:
    d = {f: getattr(e, f) for f in LIST_FIELDS}
    d["sent_at"] = e.sent_at.isoformat() if e.sent_at else None
    atts = json.loads(e.attachments or "[]")
    d["attachment_count"] = len(atts)
    c = (contacts or {}).get(e.contact_id) if e.contact_id else None
    d["contact_name"] = f"{c.first_name} {c.last_name}".strip() if c else None
    d["gmail_url"] = (f"https://mail.google.com/mail/u/{e.account}/#all/{int(e.gm_msgid):x}"
                      if e.gm_msgid.isdigit() else "https://mail.google.com/")
    return d


@router.get("")
def list_emails(q: str | None = None, direction: str | None = None, contact_id: int | None = None,
                linked: bool | None = None, include_bulk: bool = True, thread_id: str | None = None,
                date_from: date | None = None, date_to: date | None = None,
                limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = select(Email)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Email.subject.ilike(like), Email.from_email.ilike(like), Email.from_name.ilike(like),
                              Email.to_addrs.ilike(like), Email.snippet.ilike(like), Email.body_text.ilike(like)))
    if direction in ("in", "out"):
        stmt = stmt.where(Email.direction == direction)
    if contact_id:
        stmt = stmt.where(Email.contact_id == contact_id)
    if linked is True:
        stmt = stmt.where(Email.contact_id.is_not(None))
    if not include_bulk:
        stmt = stmt.where(Email.bulk.is_(False))
    if thread_id:
        stmt = stmt.where(Email.thread_id == thread_id)
    if date_from:
        stmt = stmt.where(Email.sent_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(Email.sent_at < datetime.combine(date_to + timedelta(days=1), time.min))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Email.sent_at.desc(), Email.id.desc()).limit(limit).offset(offset)).all()
    ids = {e.contact_id for e in rows if e.contact_id}
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_(ids))).all()} if ids else {}
    return {"items": [_row(e, contacts) for e in rows], "total": total}


@router.get("/{email_id}")
def get_email(email_id: int, db: Session = Depends(get_db)):
    e = get_or_404(db, Email, email_id)
    contacts = {e.contact_id: db.get(Contact, e.contact_id)} if e.contact_id else {}
    d = _row(e, {k: v for k, v in contacts.items() if v})
    d.update(body_text=e.body_text, body_html=e.body_html, attachments=json.loads(e.attachments or "[]"),
             message_id=e.message_id)
    thread = []
    if e.thread_id:
        for t in db.scalars(select(Email).where(Email.account == e.account, Email.thread_id == e.thread_id)
                            .order_by(Email.sent_at)).all():
            thread.append({"id": t.id, "direction": t.direction, "from_name": t.from_name, "from_email": t.from_email,
                           "subject": t.subject, "snippet": t.snippet, "sent_at": t.sent_at.isoformat() if t.sent_at else None})
    d["thread"] = thread
    return d


class EmailPatch(BaseModel):
    contact_id: int | None = None


@router.patch("/{email_id}")
def link_email(email_id: int, data: EmailPatch, db: Session = Depends(get_db)):
    """Link (or unlink with null) an email to a contact."""
    e = get_or_404(db, Email, email_id)
    if data.contact_id:
        get_or_404(db, Contact, data.contact_id)
    e.contact_id = data.contact_id
    db.commit()
    return get_email(email_id, db)

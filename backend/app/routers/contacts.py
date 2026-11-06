import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, ensure_exists, get_or_404
from ..models import Activity, Channel, Contact, Deal
from ..schemas import ActivityOut, ContactIn, ContactOut, ContactPage, ContactPatch, DealOut

router = APIRouter(prefix="/api/contacts", tags=["contacts"], dependencies=[Depends(current_user)])

CSV_FIELDS = ["first_name", "last_name", "email", "phone", "company", "status", "tags", "notes", "source_channel"]
VALID_STATUS = {"lead", "prospect", "customer", "inactive"}


def _filtered(q: str | None, status: str | None, channel_id: int | None, tag: str | None):
    stmt = select(Contact)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Contact.first_name.ilike(like), Contact.last_name.ilike(like),
                              Contact.email.ilike(like), Contact.company.ilike(like), Contact.phone.ilike(like)))
    if status:
        stmt = stmt.where(Contact.status == status)
    if channel_id:
        stmt = stmt.where(Contact.source_channel_id == channel_id)
    if tag:
        stmt = stmt.where(Contact.tags.ilike(f"%{tag.strip()}%"))
    return stmt


@router.get("", response_model=ContactPage)
def list_contacts(
    q: str | None = None, status: str | None = None, channel_id: int | None = None, tag: str | None = None,
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db),
):
    stmt = _filtered(q, status, channel_id, tag)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Contact.updated_at.desc()).limit(limit).offset(offset)).all()
    return ContactPage(items=items, total=total)


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(data: ContactIn, db: Session = Depends(get_db)):
    ensure_exists(db, Channel, data.source_channel_id, "Channel")
    c = Contact(**data.model_dump())
    db.add(c)
    db.commit()
    return c


@router.get("/export.csv")
def export_contacts(db: Session = Depends(get_db)):
    names = dict(db.execute(select(Channel.id, Channel.name)).all())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    for c in db.scalars(select(Contact).order_by(Contact.id)):
        row = {f: getattr(c, f) for f in CSV_FIELDS if f != "source_channel"}
        row["source_channel"] = names.get(c.source_channel_id, "")
        w.writerow(row)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=contacts.csv"})


@router.post("/import")
async def import_contacts(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import a CSV with headers matching the export format. Rows whose email already exists are skipped."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "first_name" not in [h.strip().lower() for h in reader.fieldnames]:
        raise HTTPException(422, "CSV must include a 'first_name' column")
    channels = {n.lower(): i for i, n in db.execute(select(Channel.id, Channel.name)).all()}
    existing = {e.lower() for e in db.scalars(select(Contact.email).where(Contact.email != "")).all()}
    created = skipped = 0
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        email = row.get("email", "").lower()
        if not row.get("first_name") or (email and email in existing):
            skipped += 1
            continue
        status = row.get("status", "lead").lower()
        db.add(Contact(
            first_name=row["first_name"], last_name=row.get("last_name", ""), email=email,
            phone=row.get("phone", ""), company=row.get("company", ""),
            status=status if status in VALID_STATUS else "lead",
            tags=row.get("tags", ""), notes=row.get("notes", ""),
            source_channel_id=channels.get(row.get("source_channel", "").lower()),
        ))
        if email:
            existing.add(email)
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Contact, contact_id)


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: int, data: ContactPatch, db: Session = Depends(get_db)):
    c = get_or_404(db, Contact, contact_id)
    changes = data.model_dump(exclude_unset=True)
    if "source_channel_id" in changes:
        ensure_exists(db, Channel, changes["source_channel_id"], "Channel")
    for k, v in changes.items():
        setattr(c, k, v)
    db.commit()
    return c


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Contact, contact_id))
    db.commit()


@router.get("/{contact_id}/deals", response_model=list[DealOut])
def contact_deals(contact_id: int, db: Session = Depends(get_db)):
    get_or_404(db, Contact, contact_id)
    return db.scalars(select(Deal).where(Deal.contact_id == contact_id).order_by(Deal.created_at.desc())).all()


@router.get("/{contact_id}/activities", response_model=list[ActivityOut])
def contact_activities(contact_id: int, db: Session = Depends(get_db)):
    get_or_404(db, Contact, contact_id)
    return db.scalars(select(Activity).where(Activity.contact_id == contact_id)
                      .order_by(Activity.created_at.desc())).all()

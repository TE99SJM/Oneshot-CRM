import csv
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_or_404
from ..models import Channel, Contact, Deal, Post
from ..schemas import ChannelIn, ChannelOut, ChannelPatch, ChannelStats

router = APIRouter(prefix="/api/channels", tags=["channels"], dependencies=[Depends(current_user)])


@router.get("", response_model=list[ChannelStats])
def list_channels(db: Session = Depends(get_db)):
    channels = db.scalars(select(Channel).order_by(Channel.name)).all()
    contacts = dict(db.execute(select(Contact.source_channel_id, func.count()).group_by(Contact.source_channel_id)).all())
    open_deals = dict(db.execute(select(Deal.channel_id, func.count()).where(Deal.status == "open").group_by(Deal.channel_id)).all())
    won = dict(db.execute(select(Deal.channel_id, func.sum(Deal.value)).where(Deal.status == "won").group_by(Deal.channel_id)).all())
    posts = {
        row[0]: row[1:]
        for row in db.execute(
            select(Post.channel_id, func.count(), func.sum(Post.views),
                   func.sum(Post.likes + Post.comments + Post.shares + Post.clicks)).group_by(Post.channel_id)
        ).all()
    }
    out = []
    for ch in channels:
        p = posts.get(ch.id, (0, 0, 0))
        out.append(ChannelStats(
            **ChannelOut.model_validate(ch).model_dump(),
            contacts=contacts.get(ch.id, 0), open_deals=open_deals.get(ch.id, 0),
            won_revenue=float(won.get(ch.id) or 0), posts=p[0] or 0, views=max(ch.total_views or 0, p[1] or 0), engagement=p[2] or 0,
        ))
    return out


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(data: ChannelIn, db: Session = Depends(get_db)):
    ch = Channel(**data.model_dump())
    db.add(ch)
    db.commit()
    return ch


# Header aliases: the on-screen labels (what the template uses) or the plain field names.
HEADERS = {
    "name": "name", "type": "kind", "kind": "kind", "platform": "platform", "handle": "handle", "url": "url",
    "followers / subscribers": "followers", "followers": "followers", "subscribers": "followers",
    "monthly cost (usd)": "monthly_cost", "monthly cost": "monthly_cost", "monthly_cost": "monthly_cost",
    "active": "active", "notes": "notes",
}
TEMPLATE_COLUMNS = ["Name", "Type", "Platform", "Handle", "URL", "Followers / subscribers", "Monthly cost (USD)", "Active", "Notes"]
KIND_ALIASES = {
    "social": "social", "marketplace": "marketplace", "website": "website", "website / store": "website",
    "store": "website", "website/store": "website", "email": "email", "email list": "email", "direct": "direct",
    "direct / referral": "direct", "referral": "direct", "ads": "ads", "paid ads": "ads", "other": "other",
}
KIND_LABEL = {"social": "Social", "marketplace": "Marketplace", "website": "Website / store", "email": "Email list",
              "direct": "Direct / referral", "ads": "Paid ads", "other": "Other"}


def _number(value: str, label: str, line: int) -> float | None:
    v = re.sub(r"[$,\s]", "", value or "")
    if not v:
        return None
    mult = {"k": 1_000, "m": 1_000_000}.get(v[-1].lower(), 1)
    try:
        n = float(v[:-1] if mult > 1 else v) * mult
    except ValueError:
        raise HTTPException(422, f"Row {line}: '{value}' isn't a number ({label})") from None
    if n < 0:
        raise HTTPException(422, f"Row {line}: {label} can't be negative")
    return n


@router.get("/export")
def export_channels(db: Session = Depends(get_db)):
    """CSV in the same layout the importer reads (also works as a template)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_COLUMNS)
    for c in db.scalars(select(Channel).order_by(Channel.id)):
        w.writerow([c.name, KIND_LABEL.get(c.kind, c.kind), c.platform, c.handle, c.url, c.followers,
                    f"{c.monthly_cost:g}", "TRUE" if c.active else "FALSE", c.notes])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=channels.csv"})


@router.post("/import")
async def import_channels(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import channels from CSV (comma, tab or semicolon). Rows whose Name already exists update that channel;
    blank cells leave the existing value alone."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    first = text.splitlines()[0] if text.strip() else ""
    delim = max([",", "\t", ";"], key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = next(reader, None)
    cols = [HEADERS.get((h or "").strip().lower()) for h in (header or [])]
    if "name" not in cols:
        raise HTTPException(422, "The file needs a 'Name' column. Download the template from the Channels page.")
    existing = {c.name.strip().lower(): c for c in db.scalars(select(Channel)).all()}
    created = updated = skipped = 0
    errors: list[str] = []
    for line, values in enumerate(reader, start=2):
        row = {}
        for key, val in zip(cols, values):
            if key:
                row[key] = (val or "").strip()
        name = row.get("name", "")
        if not name:
            if any(values):
                skipped += 1
            continue
        kind_raw = row.get("kind", "").lower()
        kind = KIND_ALIASES.get(kind_raw)
        if kind_raw and kind is None:
            errors.append(f"Row {line} ({name}): unknown Type '{row['kind']}', used Other")
            kind = "other"
        try:
            followers = _number(row.get("followers", ""), "Followers", line)
            cost = _number(row.get("monthly_cost", ""), "Monthly cost", line)
        except HTTPException as e:
            errors.append(f"{e.detail} - row skipped")
            skipped += 1
            continue
        active_raw = row.get("active", "").lower()
        active = None if not active_raw else active_raw in {"true", "yes", "y", "1", "x", "active"}
        ch = existing.get(name.lower())
        if ch is None:
            ch = Channel(name=name[:120], kind=kind or "social", active=True if active is None else active)
            db.add(ch)
            existing[name.lower()] = ch
            created += 1
        else:
            updated += 1
            if kind:
                ch.kind = kind
            if active is not None:
                ch.active = active
        for field in ("platform", "handle", "url", "notes"):
            if row.get(field):
                setattr(ch, field, row[field][:{"url": 500, "handle": 120}.get(field, 20000)])
        if row.get("platform"):
            ch.platform = row["platform"].lower()[:60]
        if followers is not None:
            ch.followers = int(followers)
        if cost is not None:
            ch.monthly_cost = round(cost, 2)
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}



@router.get("/{channel_id}", response_model=ChannelOut)
def get_channel(channel_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Channel, channel_id)


@router.patch("/{channel_id}", response_model=ChannelOut)
def update_channel(channel_id: int, data: ChannelPatch, db: Session = Depends(get_db)):
    ch = get_or_404(db, Channel, channel_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(ch, k, v)
    db.commit()
    return ch


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Channel, channel_id))
    db.commit()

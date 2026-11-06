from fastapi import APIRouter, Depends
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
            won_revenue=float(won.get(ch.id) or 0), posts=p[0] or 0, views=p[1] or 0, engagement=p[2] or 0,
        ))
    return out


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(data: ChannelIn, db: Session = Depends(get_db)):
    ch = Channel(**data.model_dump())
    db.add(ch)
    db.commit()
    return ch


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

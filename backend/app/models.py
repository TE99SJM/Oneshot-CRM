"""SQLAlchemy ORM models."""
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Channel(Base):
    """A social account, marketplace, website, email list or other sales channel."""
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), default="social")      # social|marketplace|website|email|direct|ads|other
    platform: Mapped[str] = mapped_column(String(60), default="")       # youtube, facebook, rumble, etsy...
    handle: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    followers: Mapped[int] = mapped_column(Integer, default=0)
    monthly_cost: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    company: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="lead")      # lead|prospect|customer|inactive
    source_channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    tags: Mapped[str] = mapped_column(String(500), default="")          # comma separated
    notes: Mapped[str] = mapped_column(Text, default="")
    external_source: Mapped[str] = mapped_column(String(30), default="", index=True)   # youtube|facebook|square|rumble
    external_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    source_channel: Mapped[Channel | None] = relationship()


class Funnel(Base):
    __tablename__ = "funnels"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    stages: Mapped[list["FunnelStage"]] = relationship(
        back_populates="funnel", cascade="all, delete-orphan", order_by="FunnelStage.position"
    )


class FunnelStage(Base):
    __tablename__ = "funnel_stages"
    id: Mapped[int] = mapped_column(primary_key=True)
    funnel_id: Mapped[int] = mapped_column(ForeignKey("funnels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer, default=0)
    probability: Mapped[int] = mapped_column(Integer, default=10)        # 0-100, used for weighted pipeline
    kind: Mapped[str] = mapped_column(String(10), default="open")        # open|won|lost

    funnel: Mapped[Funnel] = relationship(back_populates="stages")


class Deal(Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    value: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(10), default="open")      # open|won|lost (derived from stage kind)
    funnel_id: Mapped[int] = mapped_column(ForeignKey("funnels.id", ondelete="CASCADE"))
    stage_id: Mapped[int] = mapped_column(ForeignKey("funnel_stages.id", ondelete="CASCADE"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    expected_close: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    external_source: Mapped[str] = mapped_column(String(30), default="", index=True)   # youtube|facebook|square|rumble
    external_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    stage: Mapped[FunnelStage] = relationship()
    contact: Mapped[Contact | None] = relationship()
    channel: Mapped[Channel | None] = relationship()


class Post(Base):
    """A piece of social content in the content calendar."""
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="idea")      # idea|draft|scheduled|published
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    url: Mapped[str] = mapped_column(String(500), default="")
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    external_source: Mapped[str] = mapped_column(String(30), default="", index=True)   # youtube|facebook|square|rumble
    external_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    channel: Mapped[Channel | None] = relationship()


class Activity(Base):
    """Notes, calls, emails, DMs and follow-up tasks tied to a contact and/or deal."""
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="note")        # note|call|email|meeting|dm|task
    summary: Mapped[str] = mapped_column(Text)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Integration(Base):
    """A connection to an external platform that syncs data into the CRM."""
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))                    # youtube|facebook|square|rumble
    name: Mapped[str] = mapped_column(String(120), default="")
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    config: Mapped[str] = mapped_column(Text, default="{}")              # JSON, non-secret settings
    secrets: Mapped[str] = mapped_column(Text, default="")               # Fernet-encrypted JSON
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(10), default="never")  # never|ok|error|running
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_result: Mapped[str] = mapped_column(Text, default="{}")         # JSON summary of last sync
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    channel: Mapped[Channel | None] = relationship()


class Order(Base):
    """A sales order pulled from a store integration (Square, eBay). ``raw`` keeps the full original record."""
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), default="square", index=True)
    external_id: Mapped[str] = mapped_column(String(120), index=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    location_id: Mapped[str] = mapped_column(String(60), default="")
    location_name: Mapped[str] = mapped_column(String(160), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")          # ticket / reference / short id
    state: Mapped[str] = mapped_column(String(20), default="", index=True)   # OPEN|COMPLETED|CANCELED|DRAFT
    source_name: Mapped[str] = mapped_column(String(120), default="")        # e.g. "Square Online", "Point of Sale"
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    customer_email: Mapped[str] = mapped_column(String(255), default="")
    customer_phone: Mapped[str] = mapped_column(String(60), default="")
    buyer_username: Mapped[str] = mapped_column(String(120), default="", index=True)   # eBay buyer username
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    discount_total: Mapped[float] = mapped_column(Float, default=0.0)
    tax_total: Mapped[float] = mapped_column(Float, default=0.0)
    tip_total: Mapped[float] = mapped_column(Float, default=0.0)
    service_charge_total: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    refunded: Mapped[float] = mapped_column(Float, default=0.0)
    net: Mapped[float] = mapped_column(Float, default=0.0)
    processing_fee: Mapped[float] = mapped_column(Float, default=0.0)
    item_count: Mapped[float] = mapped_column(Float, default=0.0)
    items_summary: Mapped[str] = mapped_column(Text, default="")
    fulfillment_type: Mapped[str] = mapped_column(String(40), default="")
    fulfillment_state: Mapped[str] = mapped_column(String(40), default="")
    payment_summary: Mapped[str] = mapped_column(String(200), default="")
    receipt_url: Mapped[str] = mapped_column(String(500), default="")
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at_ext: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="{}")
    payments: Mapped[str] = mapped_column(Text, default="[]")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    channel: Mapped[Channel | None] = relationship()
    contact: Mapped[Contact | None] = relationship()

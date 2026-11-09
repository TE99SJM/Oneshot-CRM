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
    total_views: Mapped[int] = mapped_column(Integer, default=0)       # lifetime views (all videos/posts)
    monthly_cost: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    display_metrics: Mapped[str] = mapped_column(Text, default="")    # JSON list of metric keys to show; "" = defaults
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


class Email(Base):
    """An email message pulled from a mailbox integration (Gmail over IMAP)."""
    __tablename__ = "emails"
    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), index=True)             # the mailbox it came from
    uid: Mapped[int] = mapped_column(Integer, default=0)
    uidvalidity: Mapped[int] = mapped_column(Integer, default=0)
    gm_msgid: Mapped[str] = mapped_column(String(40), default="", index=True)
    thread_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    message_id: Mapped[str] = mapped_column(String(500), default="")
    direction: Mapped[str] = mapped_column(String(4), default="in")           # in|out
    from_name: Mapped[str] = mapped_column(String(200), default="")
    from_email: Mapped[str] = mapped_column(String(255), default="", index=True)
    to_addrs: Mapped[str] = mapped_column(Text, default="")                   # "Name <a@b>, ..."
    cc_addrs: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    snippet: Mapped[str] = mapped_column(String(400), default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_html: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[str] = mapped_column(Text, default="[]")               # JSON [{name, type, size}]
    labels: Mapped[str] = mapped_column(String(1000), default="")
    unread: Mapped[bool] = mapped_column(Boolean, default=False)
    bulk: Mapped[bool] = mapped_column(Boolean, default=False)               # newsletters / no-reply senders
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MediaFile(Base):
    """A photo or video uploaded in Compose, stored under DATA_DIR/media."""
    __tablename__ = "media_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)   # unguessable id for the public link
    filename: Mapped[str] = mapped_column(String(255), default="")            # original name
    stored_name: Mapped[str] = mapped_column(String(120))
    jpeg_name: Mapped[str] = mapped_column(String(120), default="")           # JPEG copy for Instagram (images)
    mime: Mapped[str] = mapped_column(String(100), default="")
    kind: Mapped[str] = mapped_column(String(10), default="image")             # image|video
    size: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PublishJob(Base):
    """One Compose submission: the same text/media sent to one or more platforms."""
    __tablename__ = "publish_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")               # video title (YouTube / Facebook video)
    text: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(1000), default="")
    media_ids: Mapped[str] = mapped_column(Text, default="[]")                # JSON list of MediaFile ids, in order
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)   # UTC; None = now
    status: Mapped[str] = mapped_column(String(12), default="scheduled", index=True)  # scheduled|posting|done|partial|failed|canceled
    media_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    targets: Mapped[list["PublishTarget"]] = relationship(back_populates="job", cascade="all, delete-orphan",
                                                          order_by="PublishTarget.id")


class PublishTarget(Base):
    """Where one PublishJob goes (a Facebook Page, an Instagram account, a YouTube channel)."""
    __tablename__ = "publish_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("publish_jobs.id", ondelete="CASCADE"), index=True)
    integration_id: Mapped[int | None] = mapped_column(ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String(20))                         # facebook|instagram|youtube
    name: Mapped[str] = mapped_column(String(120), default="")
    options: Mapped[str] = mapped_column(Text, default="{}")                  # JSON per-platform options
    status: Mapped[str] = mapped_column(String(12), default="pending")       # pending|posting|processing|posted|failed|canceled
    external_id: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped[PublishJob] = relationship(back_populates="targets")


class StatSnapshot(Base):
    """One saved reading per metric per day, for numbers that have no history of their own (e.g. audience)."""
    __tablename__ = "stat_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    metric: Mapped[str] = mapped_column(String(40), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)                       # UTC day
    value: Mapped[float] = mapped_column(Float, default=0.0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Conversation(Base):
    """A message thread pulled from a platform (TikTok Shop buyer chat, TikTok direct messages)."""
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), index=True)                # tiktok_shop|tiktok_business
    integration_id: Mapped[int | None] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(200), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")                # the other person's name
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    peer_id: Mapped[str] = mapped_column(String(200), default="")              # their id on the platform
    last_message: Mapped[str] = mapped_column(String(300), default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    unread: Mapped[int] = mapped_column(Integer, default=0)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=True)
    reply_note: Mapped[str] = mapped_column(String(300), default="")           # why replying is limited
    extra: Mapped[str] = mapped_column(Text, default="{}")

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan",
                                                     order_by="Message.sent_at")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    direction: Mapped[str] = mapped_column(String(4), default="in")          # in|out
    sender_name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(30), default="TEXT")
    body: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="{}")

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class NotifySettings(Base):
    """Order alerts to your phone (one row). ``secrets`` is Fernet-encrypted JSON (tokens, app passwords)."""
    __tablename__ = "notify_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    config: Mapped[str] = mapped_column(Text, default="{}")
    secrets: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[str] = mapped_column(Text, default="[]")       # last 25 alerts and what happened
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ChannelMetric(Base):
    """Every number an API gave us for a channel (latest value). One row per channel + metric key."""
    __tablename__ = "channel_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(160), default="")
    value: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(12), default="num")        # num|money|pct|seconds|minutes|hours|stars
    section: Mapped[str] = mapped_column(String(40), default="General")  # Audience, Views, Engagement, Sales...
    window: Mapped[str] = mapped_column(String(12), default="now")      # now|28d|30d|60d|live|all
    combine: Mapped[str] = mapped_column(String(8), default="sum")      # sum|avg|none (how the dashboard adds channels)
    provider: Mapped[str] = mapped_column(String(30), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MetricSnapshot(Base):
    """Daily reading of a channel metric, so the dashboard can show change over any period."""
    __tablename__ = "metric_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)

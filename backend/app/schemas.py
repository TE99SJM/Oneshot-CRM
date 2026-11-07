"""Pydantic request/response schemas."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChannelKind = Literal["social", "marketplace", "website", "email", "direct", "ads", "other"]
ContactStatus = Literal["lead", "prospect", "customer", "inactive"]
StageKind = Literal["open", "won", "lost"]
PostStatus = Literal["idea", "draft", "scheduled", "published"]
ActivityKind = Literal["note", "call", "email", "meeting", "dm", "task"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class AuthStatus(BaseModel):
    needs_setup: bool
    app_name: str


class SetupIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(default="", max_length=120)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Enter a valid email address")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(ORM):
    id: int
    email: str
    name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


# ---------- Channels ----------
class ChannelBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ChannelKind = "social"
    platform: str = ""
    handle: str = ""
    url: str = ""
    followers: int = Field(default=0, ge=0)
    monthly_cost: float = Field(default=0, ge=0)
    active: bool = True
    notes: str = ""


class ChannelIn(ChannelBase):
    pass


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: ChannelKind | None = None
    platform: str | None = None
    handle: str | None = None
    url: str | None = None
    followers: int | None = Field(default=None, ge=0)
    monthly_cost: float | None = Field(default=None, ge=0)
    active: bool | None = None
    notes: str | None = None


class ChannelOut(ChannelBase, ORM):
    id: int
    total_views: int = 0          # lifetime views reported by the platform (or the sum of synced posts)
    created_at: datetime


class ChannelStats(ChannelOut):
    contacts: int = 0
    open_deals: int = 0
    won_revenue: float = 0
    posts: int = 0
    views: int = 0
    engagement: int = 0


# ---------- Contacts ----------
class ContactBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""
    status: ContactStatus = "lead"
    source_channel_id: int | None = None
    tags: str = ""
    notes: str = ""


class ContactIn(ContactBase):
    pass


class ContactPatch(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    status: ContactStatus | None = None
    source_channel_id: int | None = None
    tags: str | None = None
    notes: str | None = None


class ContactOut(ContactBase, ORM):
    external_source: str = ""
    external_id: str = ""
    id: int
    created_at: datetime
    updated_at: datetime


class ContactPage(BaseModel):
    items: list[ContactOut]
    total: int


# ---------- Funnels ----------
class StageIn(BaseModel):
    id: int | None = None                      # present when editing an existing stage
    name: str = Field(min_length=1, max_length=80)
    probability: int = Field(default=10, ge=0, le=100)
    kind: StageKind = "open"


class StageOut(ORM):
    id: int
    name: str
    position: int
    probability: int
    kind: StageKind


class FunnelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    stages: list[StageIn] | None = None        # omitted -> default stages on create, unchanged on update


class FunnelOut(ORM):
    id: int
    name: str
    description: str
    created_at: datetime
    stages: list[StageOut]


# ---------- Deals ----------
class DealBase(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    value: float = Field(default=0, ge=0)
    funnel_id: int
    stage_id: int
    contact_id: int | None = None
    channel_id: int | None = None
    expected_close: date | None = None
    notes: str = ""


class DealIn(DealBase):
    pass


class DealPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    value: float | None = Field(default=None, ge=0)
    stage_id: int | None = None
    contact_id: int | None = None
    channel_id: int | None = None
    expected_close: date | None = None
    notes: str | None = None


class DealOut(DealBase, ORM):
    external_source: str = ""
    external_id: str = ""
    id: int
    status: StageKind
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------- Posts ----------
class PostBase(BaseModel):
    channel_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    status: PostStatus = "idea"
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    url: str = ""
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)


class PostIn(PostBase):
    pass


class PostPatch(BaseModel):
    channel_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = None
    status: PostStatus | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    url: str | None = None
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)


class PostOut(PostBase, ORM):
    external_source: str = ""
    external_id: str = ""
    id: int
    created_at: datetime


# ---------- Activities ----------
class ActivityIn(BaseModel):
    kind: ActivityKind = "note"
    summary: str = Field(min_length=1)
    contact_id: int | None = None
    deal_id: int | None = None
    due_at: datetime | None = None
    done: bool = False


class ActivityPatch(BaseModel):
    kind: ActivityKind | None = None
    summary: str | None = Field(default=None, min_length=1)
    due_at: datetime | None = None
    done: bool | None = None


class ActivityOut(ActivityIn, ORM):
    id: int
    created_at: datetime

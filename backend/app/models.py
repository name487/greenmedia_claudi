"""Database models (blueprint §4). Every business row carries tenant_id so the internal tool
can become a multi-tenant SaaS without a rebuild; every query in the routers filters on it."""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(20), default="agency")
    notify_on_negative_review: Mapped[bool] = mapped_column(Boolean, default=True)
    require_client_approval: Mapped[bool] = mapped_column(Boolean, default=False)


class Role(Base):
    """Per-tenant role: which app sections it can open and which actions it may perform (blueprint: roles table)."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(30))  # slug: admin | account_manager | seo | content | designer | client
    label: Mapped[str] = mapped_column(String(60))
    sections: Mapped[list] = mapped_column(JSON, default=list)
    permissions: Mapped[list] = mapped_column(JSON, default=list)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        # Every user's role must exist for their tenant.
        ForeignKeyConstraint(["tenant_id", "role"], ["roles.tenant_id", "roles.name"], name="fk_users_role_roles"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(30))  # roles.name within the same tenant
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)  # client-portal users
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    company_name: Mapped[str] = mapped_column(String(200))
    website: Mapped[str] = mapped_column(String(300), default="")
    industry: Mapped[str] = mapped_column(String(100), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="onboarding")  # active | onboarding | paused
    plan: Mapped[str] = mapped_column(String(20), default="Starter")
    services: Mapped[list] = mapped_column(JSON, default=list)
    account_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", use_alter=True), nullable=True)
    brand_voice: Mapped[dict] = mapped_column(JSON, default=dict)
    # Safety: empty = human approval on every channel. Keys: "reviews", "gmb", "facebook", ...
    auto_publish: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")

    contacts: Mapped[list["ClientContact"]] = relationship(cascade="all, delete-orphan")
    gmb: Mapped["GmbAccount | None"] = relationship(cascade="all, delete-orphan", uselist=False)
    social_accounts: Mapped[list["SocialAccount"]] = relationship(cascade="all, delete-orphan")


class ClientContact(Base):
    __tablename__ = "client_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    designation: Mapped[str] = mapped_column(String(80), default="")


class GmbAccount(Base):
    __tablename__ = "gmb_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), unique=True)
    location_id: Mapped[str] = mapped_column(String(100))
    oauth_ref: Mapped[str] = mapped_column(String(200), default="")  # pointer to encrypted token in a secrets store
    status: Mapped[str] = mapped_column(String(20), default="connected")  # connected | disconnected | expired
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rating: Mapped[float] = mapped_column(Float, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    # Live link to a real Google Business Profile. When connection_id is NULL the profile is simulated (demo data).
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("google_connections.id"), nullable=True)
    google_account: Mapped[str] = mapped_column(String(100), default="")  # "accounts/123"
    title: Mapped[str] = mapped_column(String(200), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")

    connection: Mapped["GoogleConnection | None"] = relationship()

    @property
    def is_live(self) -> bool:
        return self.connection_id is not None


class GoogleConnection(Base):
    """A Google account that granted the agency Business Profile access (OAuth). The refresh token is encrypted."""

    __tablename__ = "google_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(200))
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | revoked
    last_error: Mapped[str] = mapped_column(Text, default="")
    connected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))  # facebook | instagram | linkedin | youtube | x
    handle: Mapped[str] = mapped_column(String(100), default="")
    oauth_ref: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="connected")  # connected | expired


class Review(Base):
    __tablename__ = "gmb_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    external_review_id: Mapped[str] = mapped_column(String(100))
    author: Mapped[str] = mapped_column(String(120))
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")
    sentiment: Mapped[str] = mapped_column(String(10))  # positive | neutral | negative
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_status: Mapped[str] = mapped_column(String(20), default="new")  # new | drafted | approved | published | rejected | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContentItem(Base):
    __tablename__ = "content_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    topic: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(20), default="post")
    master_copy: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    creative_brief: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | in_review | scheduled | published | failed
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    variants: Mapped[list["ContentVariant"]] = relationship(cascade="all, delete-orphan", order_by="ContentVariant.id")


class ContentVariant(Base):
    __tablename__ = "content_variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    copy: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10))
    external_post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Keyword(Base):
    __tablename__ = "seo_keywords"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(200))
    target_url: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(100), default="")
    current_rank: Mapped[int] = mapped_column(Integer)
    previous_rank: Mapped[int] = mapped_column(Integer)
    volume: Mapped[int] = mapped_column(Integer, default=0)


class MetricDaily(Base):
    """One row per client per day, aggregated from GMB, GSC, GA4 and social APIs."""

    __tablename__ = "analytics_daily"
    __table_args__ = (UniqueConstraint("client_id", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    gmb_views: Mapped[int] = mapped_column(Integer, default=0)
    gmb_calls: Mapped[int] = mapped_column(Integer, default=0)
    gmb_directions: Mapped[int] = mapped_column(Integer, default=0)
    web_clicks: Mapped[int] = mapped_column(Integer, default=0)
    organic_sessions: Mapped[int] = mapped_column(Integer, default=0)
    social_reach: Mapped[int] = mapped_column(Integer, default=0)
    engagement: Mapped[int] = mapped_column(Integer, default=0)
    leads: Mapped[int] = mapped_column(Integer, default=0)


METRIC_FIELDS = ["gmb_views", "gmb_calls", "gmb_directions", "web_clicks", "organic_sessions", "social_reach", "engagement", "leads"]


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="todo")  # todo | in_progress | review | done


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="template")  # ai | template
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_via: Mapped[str | None] = mapped_column(String(20), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(300))
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

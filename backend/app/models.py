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
    # Mobile number in E.164 (+919876543210) for OTP sign-in. Several accounts may share one number — e.g. an owner of
    # two businesses — and the app then asks which profile to open.
    phone: Mapped[str] = mapped_column(String(20), default="", index=True)


class OtpChallenge(Base):
    """A one-time sign-in code sent by SMS. Only a hash is stored; it expires, allows a few attempts, and is used once."""

    __tablename__ = "otp_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


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
    # Google Post (app): {"daily": bool — the Content Agent drafts a text post a day, "auto": bool — post them without
    # asking (a standing approval, approval_rule = "auto_google_post"), "auto_by": user id who turned it on, "time": "HH:MM"}
    google_posts: Mapped[dict] = mapped_column(JSON, default=dict)
    # My Plan (app): the paid plan and until when it runs (India date), and billing details for invoices
    plan_key: Mapped[str] = mapped_column(String(30), default="")
    plan_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing: Mapped[dict] = mapped_column(JSON, default=dict)  # {gstin, billing_address, shipping_same, shipping_address}
    notes: Mapped[str] = mapped_column(Text, default="")

    # Primary contact first, then in the order they were added.
    contacts: Mapped[list["ClientContact"]] = relationship(
        cascade="all, delete-orphan", order_by=lambda: [ClientContact.is_primary.desc(), ClientContact.id])
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
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


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
    # Agency-level Google account this location is reached through (NULL when using the client's own sign-in).
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("google_connections.id"), nullable=True)
    google_account: Mapped[str] = mapped_column(String(100), default="")  # "accounts/123"
    title: Mapped[str] = mapped_column(String(200), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    maps_uri: Mapped[str] = mapped_column(String(500), default="")
    review_uri: Mapped[str] = mapped_column(String(500), default="")  # Google's "write a review" link (metadata.newReviewUri)
    # The client's own Google sign-in (per-client OAuth). Tokens are Fernet-encrypted; the access token is
    # cached here with its expiry and refreshed from the refresh token shortly before it runs out.
    google_email: Mapped[str] = mapped_column(String(200), default="")
    scopes: Mapped[str] = mapped_column(Text, default="")
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="")
    access_token_enc: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_status: Mapped[str] = mapped_column(String(20), default="")  # "" (none) | active | revoked

    connection: Mapped["GoogleConnection | None"] = relationship()

    @property
    def has_own_token(self) -> bool:
        return bool(self.refresh_token_enc) and self.token_status != "revoked"

    @property
    def is_live(self) -> bool:
        """Linked to a real Google location, through an agency connection or the client's own sign-in.
        Otherwise the profile is simulated (demo data)."""
        return bool(self.google_account) and (self.connection_id is not None or bool(self.refresh_token_enc))


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
    access_token_enc: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    # Live link (Meta): Facebook Page id / Instagram professional account id, and the Page access token (Fernet-encrypted).
    # Without them the account is simulated (demo data).
    external_id: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    access_token_enc: Mapped[str] = mapped_column(Text, default="")
    meta_connection_id: Mapped[int | None] = mapped_column(ForeignKey("meta_connections.id"), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_live(self) -> bool:
        return bool(self.external_id and self.access_token_enc)


class MetaConnection(Base):
    """A Facebook user who granted the agency access to their Pages (and linked Instagram accounts).
    The long-lived user token (~60 days) is only used to list Pages; posting uses each Page's own token."""

    __tablename__ = "meta_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "fb_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    fb_user_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    user_token_enc: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | expired
    last_error: Mapped[str] = mapped_column(Text, default="")
    connected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MetaConnectAttempt(Base):
    """One "Connect Facebook / Instagram" tap from the app: the app opens Facebook's login, then polls this row to
    learn whether the connection finished, failed (and why), or needs the owner to pick one of several Pages."""

    __tablename__ = "meta_connect_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    platform: Mapped[str] = mapped_column(String(20))  # facebook | instagram
    # pending → connected | choose_page | failed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reason: Mapped[str] = mapped_column(String(40), default="")  # cancelled | permissions | no_pages | no_instagram | page_taken | error
    message: Mapped[str] = mapped_column(Text, default="")
    candidates: Mapped[list] = mapped_column(JSON, default=list)  # Pages to choose from (no tokens)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("meta_connections.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Google's updateTime (edits)
    reviewer_photo: Mapped[str] = mapped_column(String(500), default="")
    # Who wrote the current reply text: ai | template | human (edited) | google (replied on Google directly)
    reply_source: Mapped[str] = mapped_column(String(20), default="")
    reply_model: Mapped[str] = mapped_column(String(80), default="")  # e.g. "openai/gpt-4.1-mini"
    reply_error: Mapped[str] = mapped_column(Text, default="")  # why the AI wasn't used for the last draft
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Approval of the current reply text. Nothing is published without it: set by Approve (approved_by = the user) or by
    # the client's opt-in auto-publish rule (approval_rule = "auto_publish"); cleared whenever the text changes.
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_rule: Mapped[str] = mapped_column(String(40), default="")

    @property
    def is_sample(self) -> bool:
        """Sample/demo review (not from Google): replies are never sent to Google and it is removed when real data arrives."""
        return self.external_review_id.startswith(SAMPLE_REVIEW_PREFIX)


SAMPLE_REVIEW_PREFIX = "demo_"


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
    # draft → (in_review →) scheduled → publishing → published | failed. "publishing" is held only while a worker posts.
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)  # UTC
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # publish attempts for the current schedule
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # retry after a temporary error
    last_error: Mapped[str] = mapped_column(Text, default="")
    ai_source: Mapped[str] = mapped_column(String(20), default="")  # ai | template | "" (written by hand)
    ai_model: Mapped[str] = mapped_column(String(80), default="")
    image_url: Mapped[str] = mapped_column(String(1000), default="")  # public https image (required by Instagram)
    # AI posts from the app: a rendered poster (image) or viral video. Videos are rendered in the background:
    # status "generating" (gen_progress = steps done) → "in_review", or "gen_failed" with gen_error.
    media_type: Mapped[str] = mapped_column(String(10), default="")  # "" | image | video | text (Google Post)
    target_keyword: Mapped[str] = mapped_column(String(200), default="")  # the search term a Google Post is written around
    video_url: Mapped[str] = mapped_column(String(1000), default="")
    template: Mapped[str] = mapped_column(String(40), default="")
    gen_progress: Mapped[int] = mapped_column(Integer, default=0)
    gen_error: Mapped[str] = mapped_column(Text, default="")
    product_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Approval of the current copy (Approve & schedule, or created/scheduled by someone allowed to approve). Cleared when
    # the copy changes; the publisher refuses anything without it.
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_rule: Mapped[str] = mapped_column(String(40), default="")  # "" = a person approved; "auto_google_post" = standing approval

    variants: Mapped[list["ContentVariant"]] = relationship(cascade="all, delete-orphan", order_by="ContentVariant.id")


class ContentVariant(Base):
    __tablename__ = "content_variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    copy: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10))
    external_post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | published | failed (per platform)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")


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


class SearchKeyword(Base):
    """What people typed on Google Search/Maps before the business profile appeared, with how often it appeared
    (Business Profile Performance API, searchkeywords.impressions.monthly). Replaced on every sync."""

    __tablename__ = "gmb_search_keywords"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(200))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    below_threshold: Mapped[bool] = mapped_column(Boolean, default=False)  # Google only says "fewer than N"
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)


class ProductItem(Base):
    """A product or service the business sells, with a photo — the raw material for AI posters and viral videos."""

    __tablename__ = "product_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[str] = mapped_column(String(40), default="")
    image_path: Mapped[str] = mapped_column(String(300), default="")  # relative to MEDIA_DIR
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GoogleMedia(Base):
    """A photo or video the owner adds to their Google profile from the app (Google Media). Uploaded on its day by the
    scheduler; like posts, only once approved (approved_at set — by the uploader when they may approve)."""

    __tablename__ = "google_media"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="photo")  # photo | video
    category: Mapped[str] = mapped_column(String(30), default="ADDITIONAL")  # Google's locationAssociation.category
    path: Mapped[str] = mapped_column(String(300))  # relative to MEDIA_DIR
    thumb_path: Mapped[str] = mapped_column(String(300), default="")
    # pending (needs approval) | scheduled | publishing | uploaded | failed
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_name: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlanPayment(Base):
    """One plan purchase from the app. Paid only when Razorpay says so (signed callback or webhook) — never on the app's word."""

    __tablename__ = "plan_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    plan_key: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(Integer)  # paise, after any coupon
    list_amount: Mapped[int] = mapped_column(Integer)  # paise, before the coupon
    coupon: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="created", index=True)  # created | paid | failed | expired
    provider: Mapped[str] = mapped_column(String(20), default="razorpay")  # razorpay | demo
    link_id: Mapped[str] = mapped_column(String(80), default="", index=True)  # Razorpay payment link id
    payment_ref: Mapped[str] = mapped_column(String(80), default="")  # Razorpay payment id once paid
    checkout_url: Mapped[str] = mapped_column(String(500), default="")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Competitor(Base):
    """A nearby business the client is compared against on the Business Score screen."""

    __tablename__ = "competitors"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    rating: Mapped[float] = mapped_column(Float, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    maps_uri: Mapped[str] = mapped_column(String(500), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)  # from the client; ≤5 km counts as local
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ScoreSnapshot(Base):
    """The Business Score once a day, for the "Growth in Marketing Score" chart."""

    __tablename__ = "score_snapshots"
    __table_args__ = (UniqueConstraint("client_id", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    value: Mapped[int] = mapped_column(Integer)


class KeywordSearchLog(Base):
    """One Keyword Planner search; counted against the client's monthly search credits."""

    __tablename__ = "keyword_searches"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    keyword: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


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
    # Structured context, e.g. for review replies: before/after text, AI provider/model/tokens, Google response, errors
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

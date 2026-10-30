import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _db_url(url: str) -> str:
    """Hosting platforms hand out postgres://… — SQLAlchemy needs the driver: postgresql+psycopg://…"""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _url(value: str) -> str:
    value = value.strip().rstrip("/")
    return value if "://" in value else f"https://{value}"



def first_set(env, *names: str) -> str:
    """The first of these settings that has a value (several names are accepted for the same thing)."""
    return next((v.strip() for v in (env.get(n) for n in names) if v and v.strip()), "")


def sms_provider_from(env) -> str:
    """SMS_PROVIDER, or nimbusit when only SMS_AUTHKEY is filled. An empty `SMS_PROVIDER=` line counts as not set."""
    chosen = (env.get("SMS_PROVIDER") or "").strip().lower()
    return chosen or ("nimbusit" if (env.get("SMS_AUTHKEY") or "").strip() else "console")

class Settings:
    database_url: str = _db_url(os.getenv("DATABASE_URL", f"sqlite:///{Path(__file__).resolve().parents[1] / 'greenmedia.db'}"))
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    jwt_ttl_minutes: int = int(os.getenv("JWT_TTL_MINUTES", "720"))
    seed_demo: bool = os.getenv("SEED_DEMO", "1") == "1"
    # AI Review Queue: show clearly-labelled sample reviews while Google hasn't approved Business Profile API
    # access (quota 0) or a client isn't linked yet. Set to 0 to never create sample reviews.
    review_sample_data: bool = os.getenv("REVIEW_SAMPLE_DATA", "1") == "1"
    review_autodraft_limit: int = int(os.getenv("REVIEW_AUTODRAFT_LIMIT", "20"))  # AI drafts per client per sync
    # "openai" or "anthropic". Unset: OpenAI when OPENAI_API_KEY is set, else Anthropic.
    ai_provider: str = (os.getenv("AI_PROVIDER") or ("openai" if os.getenv("OPENAI_API_KEY") else "anthropic")).lower()
    ai_model: str = os.getenv("AI_MODEL", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    # Official OpenAI API by default; point at a compatible gateway (e.g. Azure OpenAI proxy) if needed
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    openai_org: str = os.getenv("OPENAI_ORG_ID", "")
    openai_project: str = os.getenv("OPENAI_PROJECT_ID", "")
    # Google Business Profile (OAuth web client from Google Cloud Console)
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # Must exactly match an "Authorized redirect URI" on the OAuth client, e.g. https://api.example.com/api/google/callback
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8001/api/google/callback")
    # Where the browser lands after connecting (the Django "Google Business Profile" page)
    web_app_url: str = _url(os.getenv("WEB_APP_URL", "http://127.0.0.1:8000"))
    # Meta (Facebook Pages + Instagram professional accounts) — app from developers.facebook.com, "Facebook Login for Business"
    meta_app_id: str = os.getenv("META_APP_ID", "")
    meta_app_secret: str = os.getenv("META_APP_SECRET", "")
    meta_redirect_uri: str = os.getenv("META_REDIRECT_URI", "http://127.0.0.1:8001/api/meta/callback")
    meta_graph_version: str = os.getenv("META_GRAPH_VERSION", "v23.0")
    # Fernet key for OAuth tokens at rest: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    # Phone OTP sign-in (mobile app). SMS_PROVIDER: console (code only in the server log — development/demo),
    # nimbusit (India: SMS_HOST, SMS_USER, SMS_AUTHKEY, SMS_SENDER and the DLT SMS_ENTITYID + SMS_TEMPLATEID, with
    # SMS_TEXT exactly as the approved template and {otp} where the code goes) or msg91 (MSG91_AUTH_KEY +
    # MSG91_TEMPLATE_ID with an ##OTP## variable).
    # Without SMS_PROVIDER, setting SMS_AUTHKEY picks nimbusit.
    sms_provider: str = sms_provider_from(os.environ)
    sms_host: str = os.getenv("SMS_HOST", "nimbusit.net")
    sms_user: str = os.getenv("SMS_USER", "")
    sms_authkey: str = os.getenv("SMS_AUTHKEY", "")
    sms_sender: str = os.getenv("SMS_SENDER", "")
    sms_entityid: str = os.getenv("SMS_ENTITYID", "")
    sms_templateid: str = os.getenv("SMS_TEMPLATEID", "")
    sms_rpt: str = os.getenv("SMS_RPT", "1")
    sms_text: str = os.getenv("SMS_TEXT", "")  # NimbusIT: the DLT-approved template, word for word, with {otp}
    msg91_auth_key: str = os.getenv("MSG91_AUTH_KEY", "")
    msg91_template_id: str = os.getenv("MSG91_TEMPLATE_ID", "")
    otp_length: int = int(os.getenv("OTP_LENGTH", "6"))
    otp_ttl_seconds: int = int(os.getenv("OTP_TTL_SECONDS", "300"))
    otp_resend_seconds: int = int(os.getenv("OTP_RESEND_SECONDS", "30"))
    otp_max_per_hour: int = int(os.getenv("OTP_MAX_PER_HOUR", "5"))
    otp_max_attempts: int = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
    # AI posts: uploaded product photos and generated posters/videos are stored here and served at /media.
    # PUBLIC_BASE_URL is how the outside world (the app, and Facebook/Instagram when publishing) reaches this API —
    # it must be https for Instagram.
    media_dir: str = os.getenv("MEDIA_DIR", str(Path(__file__).resolve().parents[1] / "media"))
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    ai_posts_monthly: int = int(os.getenv("AI_POSTS_MONTHLY", "5"))
    viral_videos_monthly: int = int(os.getenv("VIRAL_VIDEOS_MONTHLY", "5"))
    video_width: int = int(os.getenv("VIDEO_WIDTH", "720"))  # 9:16; height = width * 16 / 9
    # Keyword Planner: searches each client may run per calendar month, and weekly targets on the home screen tracker
    keyword_search_monthly_limit: int = int(os.getenv("KEYWORD_SEARCH_MONTHLY_LIMIT", "20"))
    weekly_post_target: int = int(os.getenv("WEEKLY_POST_TARGET", "5"))
    weekly_reply_target: int = int(os.getenv("WEEKLY_REPLY_TARGET", "5"))
    weekly_media_target: int = int(os.getenv("WEEKLY_MEDIA_TARGET", "3"))  # Google profile photos/videos (monthly report)

    # My Plan (app): payments through Razorpay Payment Links (a hosted Razorpay page; the app needs no payment SDK).
    # Without keys, PAYMENTS_DEMO=1 (default when SEED_DEMO=1) offers a clearly marked practice checkout instead.
    # RAZORPAY_KEY / RAZORPAY_SECRET are accepted too. A test key (rzp_test_…) runs Razorpay's test mode: real
    # checkout pages, test cards/UPI, no money moves.
    razorpay_key_id: str = first_set(os.environ, "RAZORPAY_KEY_ID", "RAZORPAY_KEY")
    razorpay_key_secret: str = first_set(os.environ, "RAZORPAY_KEY_SECRET", "RAZORPAY_SECRET")
    razorpay_webhook_secret: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    payments_demo: bool = os.getenv("PAYMENTS_DEMO", os.getenv("SEED_DEMO", "1")) == "1"
    # COUPONS="WELCOME10:10%,FESTIVE500:500" — a percentage, or rupees off
    coupons: str = os.getenv("COUPONS", "WELCOME10:10%" if os.getenv("SEED_DEMO", "1") == "1" else "")

    # Legal pages in the app (Settings → Privacy Policy / Terms of Service / Refund Request). Have a lawyer review them.
    legal_company: str = os.getenv("LEGAL_COMPANY", "Green Media")
    legal_email: str = os.getenv("LEGAL_EMAIL", "support@greenmedia.in")
    legal_address: str = os.getenv("LEGAL_ADDRESS", "Pune, Maharashtra, India")
    legal_updated: str = os.getenv("LEGAL_UPDATED", "2026-10-21")
    refund_days: int = int(os.getenv("REFUND_DAYS", "7"))
    # Redis + Celery for scheduled publishing. Set REDIS_URL (e.g. redis://127.0.0.1:6379/0) and run a worker + beat:
    #   celery -A app.celery_app worker -B -l info
    # Empty: no Celery; "publish now" runs inline and due posts go out via SCHEDULER_INTERVAL_MINUTES or cron.
    redis_url: str = os.getenv("REDIS_URL", "")
    content_max_attempts: int = int(os.getenv("CONTENT_PUBLISH_MAX_ATTEMPTS", "3"))
    content_retry_minutes: int = int(os.getenv("CONTENT_RETRY_MINUTES", "2"))  # first retry delay; doubles each time
    google_sync_minutes: int = int(os.getenv("GOOGLE_SYNC_MINUTES", "30"))  # Celery beat: review/insight sync interval
    # Background sync/publish loop inside the API process (0 = off; use `python -m app.jobs` from cron instead)
    scheduler_minutes: int = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "0"))
    cors_origins: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000").split(",") if o.strip()]

    @property
    def ai_key(self) -> str:
        return self.openai_api_key if self.ai_provider == "openai" else self.anthropic_api_key

    @property
    def model(self) -> str:
        return self.ai_model or ("gpt-4.1-mini" if self.ai_provider == "openai" else "claude-sonnet-5")

    @property
    def meta_configured(self) -> bool:
        return bool(self.meta_app_id and self.meta_app_secret)

    @property
    def celery_enabled(self) -> bool:
        return bool(self.redis_url)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()

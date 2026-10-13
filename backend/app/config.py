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

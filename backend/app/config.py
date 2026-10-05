import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{Path(__file__).resolve().parents[1] / 'greenmedia.db'}")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    jwt_ttl_minutes: int = int(os.getenv("JWT_TTL_MINUTES", "720"))
    seed_demo: bool = os.getenv("SEED_DEMO", "1") == "1"
    # AI Review Queue: show clearly-labelled sample reviews while Google hasn't approved Business Profile API
    # access (quota 0) or a client isn't linked yet. Set to 0 to never create sample reviews.
    review_sample_data: bool = os.getenv("REVIEW_SAMPLE_DATA", "1") == "1"
    review_autodraft_limit: int = int(os.getenv("REVIEW_AUTODRAFT_LIMIT", "20"))  # AI drafts per client per sync
    ai_provider: str = os.getenv("AI_PROVIDER", "anthropic").lower()
    ai_model: str = os.getenv("AI_MODEL", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    # Google Business Profile (OAuth web client from Google Cloud Console)
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # Must exactly match an "Authorized redirect URI" on the OAuth client, e.g. https://api.example.com/api/google/callback
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8001/api/google/callback")
    # Where the browser lands after connecting (the Django "Google Business Profile" page)
    web_app_url: str = os.getenv("WEB_APP_URL", "http://127.0.0.1:8000").rstrip("/")
    # Fernet key for OAuth tokens at rest: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")
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
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()

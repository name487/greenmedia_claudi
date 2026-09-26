import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{Path(__file__).resolve().parents[1] / 'greenmedia.db'}")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    jwt_ttl_minutes: int = int(os.getenv("JWT_TTL_MINUTES", "720"))
    seed_demo: bool = os.getenv("SEED_DEMO", "1") == "1"
    ai_provider: str = os.getenv("AI_PROVIDER", "anthropic").lower()
    ai_model: str = os.getenv("AI_MODEL", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    cors_origins: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",") if o.strip()]

    @property
    def ai_key(self) -> str:
        return self.openai_api_key if self.ai_provider == "openai" else self.anthropic_api_key

    @property
    def model(self) -> str:
        return self.ai_model or ("gpt-4.1-mini" if self.ai_provider == "openai" else "claude-sonnet-5")


settings = Settings()

import os
import tempfile

# Must be set before the app (and its engine) is imported.
# TEST_DATABASE_URL=postgresql+psycopg://… runs the suite against PostgreSQL (CI does both); default is a temp SQLite file.
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    _db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    os.environ["DATABASE_URL"] = f"sqlite:///{_db.name}"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["SEED_DEMO"] = "1"
os.environ["GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://testserver/api/google/callback"
os.environ["WEB_APP_URL"] = "http://web.test"
os.environ["SCHEDULER_INTERVAL_MINUTES"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    with TestClient(app) as c:
        yield c


def login(c: TestClient, email: str) -> dict:
    r = c.post("/api/auth/login", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return login(client, "admin@greenmedia.in")


@pytest.fixture()
def portal(client):
    return login(client, "anjali@smiledental.in")


@pytest.fixture()
def google(monkeypatch):
    """Route all Google HTTP traffic to an in-process fake that speaks the real API shapes."""
    import httpx

    from app.google import api

    from .test_google import FakeGoogle

    fake = FakeGoogle()
    monkeypatch.setattr(api, "http", httpx.Client(transport=httpx.MockTransport(fake)))
    return fake


@pytest.fixture()
def openai(monkeypatch):
    """Route AI calls to an in-process fake of the OpenAI Chat Completions API (provider = openai, key set)."""
    import httpx

    from app import ai
    from app.config import settings

    from .test_ai_openai import KEY, FakeOpenAI

    fake = FakeOpenAI()
    monkeypatch.setattr(ai, "http", httpx.Client(transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(ai, "RETRY_DELAY", 0)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", KEY)
    monkeypatch.setattr(settings, "ai_model", "")
    return fake

"""Run the real FastAPI app with Google, Meta and OpenAI replaced by the in-process fakes from backend/tests.

Used by e2e/run.sh. Also serves what the fakes received on http://127.0.0.1:$E2E_FAKE_PORT/ so the browser test can
check that nothing reached Google or Meta before it was approved.
"""

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_PORT = int(os.environ.get("E2E_API_PORT", "8001"))
WEB_URL = os.environ.get("E2E_WEB_URL", "http://127.0.0.1:8000")
db = Path(os.environ.get("E2E_DB", Path(tempfile.gettempdir()) / "greenmedia-e2e.db"))
db.unlink(missing_ok=True)
os.environ.update(
    DATABASE_URL=f"sqlite:///{db}", SEED_DEMO="1", REDIS_URL="", SCHEDULER_INTERVAL_MINUTES="0",
    OPENAI_API_KEY="sk-e2e-0000000000000000", AI_PROVIDER="openai", AI_MODEL="",
    GOOGLE_CLIENT_ID="437254480587-e2e.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET="e2e",
    GOOGLE_REDIRECT_URI=f"http://127.0.0.1:{API_PORT}/api/google/callback", WEB_APP_URL=WEB_URL,
    META_APP_ID="meta-app", META_APP_SECRET="meta-secret", META_REDIRECT_URI="http://testserver/api/meta/callback", META_GRAPH_VERSION="v23.0",
)
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app import ai  # noqa: E402
from app.google import api as google_api  # noqa: E402
from app.meta import api as meta_api  # noqa: E402
from tests.test_ai_openai import KEY, FakeOpenAI  # noqa: E402
from tests.test_google import FakeGoogle  # noqa: E402
from tests.test_meta import FakeMeta  # noqa: E402

os.environ["OPENAI_API_KEY"] = KEY
from app.config import settings  # noqa: E402

settings.openai_api_key = KEY
POST_JSON = json.dumps({
    "master_copy": "Monsoon smiles deserve care. Free dental check-ups all month at Smile Dental Studio, Baner. Book at https://smile.example",
    "hashtags": ["#Pune", "#Dentist", "#Monsoon"], "creative_brief": "Rainy window, bright smile, headline 'Monsoon Smile Check'",
    "variants": [{"platform": "facebook", "copy": "Rainy days, bright smiles! Free check-ups all monsoon at our Baner clinic. Book: https://smile.example"},
                 {"platform": "instagram", "copy": "Monsoon smiles ☔️ Free check-ups all month at Smile Dental Studio. Book via link in bio! #Pune #Dentist"},
                 {"platform": "gmb", "copy": "Free dental check-ups all monsoon at Smile Dental Studio, Baner. Book online today."}]})


class SmartOpenAI(FakeOpenAI):
    """Review replies get the reply text; post generation / adaptation (JSON prompts) get JSON."""

    def __call__(self, req):
        system = json.loads(req.content)["messages"][0]["content"]
        self.reply = POST_JSON if "JSON only" in system else "Hi Meena, we're truly sorry about the wait. Please call us on +91 98765 43210 so we can make it right. — Team Smile"
        return super().__call__(req)


google, meta, openai = FakeGoogle(), FakeMeta(), SmartOpenAI()
google_api.http = httpx.Client(transport=httpx.MockTransport(google))
meta_api.http = httpx.Client(transport=httpx.MockTransport(meta))
ai.http = httpx.Client(transport=httpx.MockTransport(openai))


class Inspect(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({"google_replies": google.replies, "google_posts": google.posts, "meta_posts": meta.posts,
                           "openai_requests": len(openai.requests)}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


threading.Thread(target=HTTPServer(("127.0.0.1", int(os.environ.get("E2E_FAKE_PORT", "8099"))), Inspect).serve_forever, daemon=True).start()

from app.main import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="warning")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .ai import ai_enabled
from .config import settings
from .routers import analytics, auth, clients, content, dashboard, reports, reviews, seo, tasks
from .routers import settings as settings_router
from .seed import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(seed_if_empty=settings.seed_demo)
    yield


app = FastAPI(title="Green Media AI Command Center API", version="1.0.0", lifespan=lifespan)

# Browsers only: the Django frontend calls the API server-to-server and Flutter is native, so neither needs CORS.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (auth, dashboard, clients, reviews, content, seo, analytics, reports, tasks, settings_router):
    app.include_router(r.router)


@app.get("/api/health", tags=["meta"])
def health():
    return {"ok": True, "ai": ai_enabled(), "provider": settings.ai_provider, "model": settings.model}

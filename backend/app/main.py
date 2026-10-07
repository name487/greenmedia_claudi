import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from .ai import ai_enabled
from .config import settings
from .routers import ai as ai_router
from .routers import analytics, auth, clients, content, dashboard, google, reports, reviews, seo, tasks, users
from .routers import settings as settings_router
from .seed import init_db


async def _scheduler(minutes: int) -> None:
    from .jobs import run_once

    while True:
        try:
            logging.getLogger("greenmedia.jobs").info("scheduler: %s", await run_in_threadpool(run_once))
        except Exception:  # noqa: BLE001 — never let the loop die
            logging.getLogger("greenmedia.jobs").exception("scheduler pass failed")
        await asyncio.sleep(minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(seed_if_empty=settings.seed_demo)
    # With Redis, Celery beat owns scheduling; the in-process loop is only the no-Redis fallback.
    run_loop = settings.scheduler_minutes > 0 and not settings.celery_enabled
    if settings.scheduler_minutes > 0 and settings.celery_enabled:
        logging.getLogger("greenmedia.jobs").info("REDIS_URL set: scheduling runs in Celery beat, in-process scheduler disabled")
    task = asyncio.create_task(_scheduler(settings.scheduler_minutes)) if run_loop else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Green Media AI Command Center API", version="1.0.0", lifespan=lifespan)

# Browsers only: the Django frontend calls the API server-to-server and Flutter is native, so neither needs CORS.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (auth, dashboard, clients, reviews, content, seo, analytics, reports, tasks, settings_router, google, users):
    app.include_router(r.router)
app.include_router(google.client_router)
app.include_router(ai_router.router)
app.include_router(ai_router.client_router)


@app.get("/api/health", tags=["meta"])
def health():
    return {"ok": True, "ai": ai_enabled(), "provider": settings.ai_provider, "model": settings.model, "demo": settings.seed_demo}

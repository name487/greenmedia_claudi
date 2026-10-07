"""Background jobs: sync live Google profiles and publish due scheduled content.

With Redis: Celery beat runs these (app/celery_app.py). Without Redis: inside the API
(SCHEDULER_INTERVAL_MINUTES > 0) or from cron:
    python -m app.jobs            # one pass of everything
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import review_queue
from .db import SessionLocal
from .google import api as google_api
from .models import AuditLog, Client, GmbAccount

log = logging.getLogger("greenmedia.jobs")


def _log(db: Session, tenant_id: int, action: str, client_id: int | None = None, entity: str = "", entity_id: object = "") -> None:
    db.add(AuditLog(tenant_id=tenant_id, user_id=None, client_id=client_id, action=f"[scheduler] {action}", entity_type=entity, entity_id=str(entity_id)))


def sync_google(db: Session) -> dict:
    done = failed = 0
    for gmb in db.scalars(select(GmbAccount).where(GmbAccount.google_account != "", GmbAccount.status == "connected")):
        if not gmb.is_live:
            continue
        client = db.get(Client, gmb.client_id)
        try:
            out = review_queue.sync_live(db, client)
            if out["new_reviews"]:
                _log(db, client.tenant_id, f"{out['new_reviews']} new Google reviews", client.id, "gmb_account", gmb.id)
            done += 1
        except google_api.GoogleApiError as e:
            log.warning("Google sync failed for %s: %s", client.company_name, e)
            failed += 1
        db.commit()
    return {"synced": done, "failed": failed}


def publish_due(db: Session) -> dict:
    """Publish scheduled content that is due (also retries temporary failures). See content_service."""
    from . import content_service
    return content_service.publish_due(db)


def run_once() -> dict:
    with SessionLocal() as db:
        return {"google": sync_google(db), "content": publish_due(db)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_once())

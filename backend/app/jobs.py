"""Background jobs: sync live Google profiles and publish due scheduled content.

Run inside the API (SCHEDULER_INTERVAL_MINUTES > 0) or from cron:
    python -m app.jobs            # one pass of everything
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import review_queue
from .db import SessionLocal
from .google import api as google_api
from .models import AuditLog, Client, ContentItem, GmbAccount
from .publishers import PublishError, publish_post

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
    now = datetime.now(timezone.utc)
    ok = failed = 0
    due = db.scalars(select(ContentItem).where(ContentItem.status == "scheduled", ContentItem.scheduled_at.is_not(None)))
    for item in due:
        at = item.scheduled_at if item.scheduled_at.tzinfo else item.scheduled_at.replace(tzinfo=timezone.utc)
        if at > now:
            continue
        client = db.get(Client, item.client_id)
        try:
            for v in item.variants:
                v.external_post_id = v.external_post_id or publish_post(client, v.platform, v.copy)
            item.status = "published"
            _log(db, item.tenant_id, f"published: {item.topic}", client.id, "content", item.id)
            ok += 1
        except PublishError as e:
            item.status = "failed"
            _log(db, item.tenant_id, f"publish failed: {e}", client.id, "content", item.id)
            failed += 1
        db.commit()
    return {"published": ok, "failed": failed}


def run_once() -> dict:
    with SessionLocal() as db:
        return {"google": sync_google(db), "content": publish_due(db)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_once())

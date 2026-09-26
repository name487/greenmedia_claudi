from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai import ai_enabled
from ..config import settings as cfg
from ..db import get_db
from ..models import Tenant, User
from ..security import ACTIONS, ALL_SECTIONS, ROLE_LABELS, SECTIONS, audit, require, require_section

router = APIRouter(prefix="/api/settings", tags=["settings"])

INTEGRATIONS = [
    ("Google Business Profile API", "Reviews, posts, insights"), ("Google Search Console", "Queries, clicks, positions"),
    ("Google Analytics 4", "Sessions, conversions"), ("Meta Graph API", "Facebook & Instagram publishing"),
    ("LinkedIn Marketing API", "Company page posts"), ("YouTube Data API", "Video metadata & community"),
    ("WhatsApp Business", "Report delivery & alerts"),
]


def _out(t: Tenant) -> dict:
    return {
        "tenant_name": t.name,
        "notify_on_negative_review": t.notify_on_negative_review,
        "require_client_approval": t.require_client_approval,
        "ai": {"enabled": ai_enabled(), "provider": cfg.ai_provider, "model": cfg.model},
        "integrations": [{"name": n, "description": d, "status": "not_configured"} for n, d in INTEGRATIONS],
        "roles": [{"role": r, "label": ROLE_LABELS[r], "sections": SECTIONS[r], "permissions": ACTIONS[r]} for r in ROLE_LABELS],
        "sections": ALL_SECTIONS,
    }


@router.get("")
def get_settings(user: User = Depends(require_section("settings")), db: Session = Depends(get_db)):
    return _out(db.get(Tenant, user.tenant_id))


class SettingsPatch(BaseModel):
    notify_on_negative_review: bool | None = None
    require_client_approval: bool | None = None


@router.patch("")
def patch_settings(body: SettingsPatch, user: User = Depends(require("settings.edit")), db: Session = Depends(get_db)):
    t = db.get(Tenant, user.tenant_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(t, k, v)
    audit(db, user, f"settings: {', '.join(changes)}", entity_type="settings")
    db.commit()
    return _out(t)

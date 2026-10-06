from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, Tenant, User
from ..security import ALL_SECTIONS, audit, require, require_section
from .ai import status_out as ai_status

router = APIRouter(prefix="/api/settings", tags=["settings"])

INTEGRATIONS = [
    ("Google Business Profile API", "Reviews, posts, insights"), ("Google Search Console", "Queries, clicks, positions"),
    ("Google Analytics 4", "Sessions, conversions"), ("Meta Graph API", "Facebook & Instagram publishing"),
    ("LinkedIn Marketing API", "Company page posts"), ("YouTube Data API", "Video metadata & community"),
    ("WhatsApp Business", "Report delivery & alerts"),
]


def _out(t: Tenant, roles: list[Role]) -> dict:
    return {
        "tenant_name": t.name,
        "notify_on_negative_review": t.notify_on_negative_review,
        "require_client_approval": t.require_client_approval,
        "ai": ai_status(),
        "integrations": [{"name": n, "description": d, "status": "not_configured"} for n, d in INTEGRATIONS],
        "roles": [{"role": r.name, "label": r.label, "sections": r.sections, "permissions": r.permissions} for r in roles],
        "sections": ALL_SECTIONS,
    }


def _tenant_roles(db: Session, tenant_id: int) -> list[Role]:
    return list(db.scalars(select(Role).where(Role.tenant_id == tenant_id).order_by(Role.id)))


@router.get("")
def get_settings(user: User = Depends(require_section("settings")), db: Session = Depends(get_db)):
    return _out(db.get(Tenant, user.tenant_id), _tenant_roles(db, user.tenant_id))


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
    return _out(t, _tenant_roles(db, user.tenant_id))

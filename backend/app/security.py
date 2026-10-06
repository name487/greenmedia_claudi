from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditLog, Client, Role, User

# Built-in roles. They seed the `roles` table for every tenant; after that the table is the source of truth
# (admins can change a role's sections and permissions per agency).
ROLE_LABELS = {
    "admin": "Admin",
    "account_manager": "Account Manager",
    "seo": "SEO Specialist",
    "content": "Content Writer",
    "designer": "Designer",
    "client": "Client",
}

ALL_SECTIONS = ["dashboard", "clients", "gmb", "reviews", "content", "creative", "social", "seo", "analytics", "reports", "tasks", "settings"]
ALL_ACTIONS = ["review.publish", "review.approve", "content.create", "content.approve", "content.publish", "client.edit", "report.deliver", "settings.edit"]

SECTIONS = {
    "admin": ALL_SECTIONS,
    "account_manager": [s for s in ALL_SECTIONS if s != "settings"],
    "seo": ["dashboard", "clients", "gmb", "seo", "analytics", "reports", "tasks"],
    "content": ["dashboard", "clients", "gmb", "reviews", "content", "creative", "social", "tasks"],
    "designer": ["dashboard", "clients", "content", "creative", "social", "tasks"],
    "client": ["dashboard", "reviews", "content", "analytics", "reports"],
}

ACTIONS = {
    "admin": ALL_ACTIONS,
    "account_manager": [a for a in ALL_ACTIONS if a != "settings.edit"],
    "seo": ["content.create"],
    "content": ["content.create"],
    "designer": ["content.create"],
    "client": ["review.approve", "content.approve"],
}


def ensure_default_roles(db: Session, tenant_id: int) -> None:
    """Create any built-in role the tenant is missing (new tenants, and databases from before the roles table)."""
    have = set(db.scalars(select(Role.name).where(Role.tenant_id == tenant_id)))
    for name, label in ROLE_LABELS.items():
        if name not in have:
            db.add(Role(tenant_id=tenant_id, name=name, label=label, sections=list(SECTIONS[name]), permissions=list(ACTIONS[name])))
    db.flush()


def load_role(db: Session, user: User) -> User:
    """Attach the user's role (sections, permissions, label) from the roles table. Unknown role = no access."""
    role = db.scalar(select(Role).where(Role.tenant_id == user.tenant_id, Role.name == user.role))
    user.role_label = role.label if role else user.role
    user.sections = list(role.sections) if role else []
    user.permissions = list(role.permissions) if role else []
    return user


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "tid": user.tenant_id,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if not user or user.status != "active" or user.tenant_id != payload["tid"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return load_role(db, user)


def can(user: User, action: str) -> bool:
    return action in getattr(user, "permissions", [])


def require(action: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not can(user, action):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role cannot perform {action}")
        return user

    return dep


def require_section(section: str):
    def dep(user: User = Depends(current_user)) -> User:
        if section not in getattr(user, "sections", []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role cannot access {section}")
        return user

    return dep


def visible_client_ids(db: Session, user: User) -> list[int]:
    """Clients this user may see: the whole tenant for staff, only their own company for client-portal users."""
    if user.client_id:
        return [user.client_id]
    if user.role == "client":  # portal user whose client was removed: sees nothing, never the whole agency
        return []
    return list(db.scalars(select(Client.id).where(Client.tenant_id == user.tenant_id)))


def get_client(db: Session, user: User, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client or client.tenant_id != user.tenant_id or (user.client_id and user.client_id != client_id) or (user.role == "client" and not user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    return client


def scoped_ids(db: Session, user: User, client_id: int | None) -> list[int]:
    """Resolve an optional ?client_id filter against what the user is allowed to see."""
    if client_id is None:
        return visible_client_ids(db, user)
    return [get_client(db, user, client_id).id]


def audit(db: Session, user: User | None, action: str, *, client_id: int | None = None, entity_type: str = "", entity_id: object = "",
          details: dict | None = None, tenant_id: int | None = None) -> None:
    """Append to audit_logs. user=None records a system action (scheduler, sync) and needs tenant_id."""
    db.add(AuditLog(tenant_id=user.tenant_id if user else tenant_id, user_id=user.id if user else None, client_id=client_id, action=action[:300],
                    entity_type=entity_type, entity_id=str(entity_id), details=details or None))

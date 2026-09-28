from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditLog, Client, User

ROLE_LABELS = {
    "admin": "Admin",
    "account_manager": "Account Manager",
    "seo": "SEO Specialist",
    "content": "Content Writer",
    "designer": "Designer",
    "client": "Client",
}

ALL_SECTIONS = ["dashboard", "clients", "gmb", "reviews", "content", "creative", "social", "seo", "analytics", "reports", "tasks", "settings"]

SECTIONS = {
    "admin": ALL_SECTIONS,
    "account_manager": [s for s in ALL_SECTIONS if s != "settings"],
    "seo": ["dashboard", "clients", "gmb", "seo", "analytics", "reports", "tasks"],
    "content": ["dashboard", "clients", "gmb", "reviews", "content", "creative", "social", "tasks"],
    "designer": ["dashboard", "clients", "content", "creative", "social", "tasks"],
    "client": ["dashboard", "reviews", "content", "analytics", "reports"],
}

ACTIONS = {
    "admin": ["review.publish", "review.approve", "content.create", "content.approve", "content.publish", "client.edit", "report.deliver", "settings.edit"],
    "account_manager": ["review.publish", "review.approve", "content.create", "content.approve", "content.publish", "client.edit", "report.deliver"],
    "seo": ["content.create"],
    "content": ["content.create"],
    "designer": ["content.create"],
    "client": ["review.approve", "content.approve"],
}


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
    return user


def can(user: User, action: str) -> bool:
    return action in ACTIONS.get(user.role, [])


def require(action: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not can(user, action):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role cannot perform {action}")
        return user

    return dep


def require_section(section: str):
    def dep(user: User = Depends(current_user)) -> User:
        if section not in SECTIONS.get(user.role, []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role cannot access {section}")
        return user

    return dep


def visible_client_ids(db: Session, user: User) -> list[int]:
    """Clients this user may see: the whole tenant for staff, only their own company for client-portal users."""
    if user.client_id:
        return [user.client_id]
    return list(db.scalars(select(Client.id).where(Client.tenant_id == user.tenant_id)))


def get_client(db: Session, user: User, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client or client.tenant_id != user.tenant_id or (user.client_id and user.client_id != client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    return client


def scoped_ids(db: Session, user: User, client_id: int | None) -> list[int]:
    """Resolve an optional ?client_id filter against what the user is allowed to see."""
    if client_id is None:
        return visible_client_ids(db, user)
    return [get_client(db, user, client_id).id]


def audit(db: Session, user: User, action: str, *, client_id: int | None = None, entity_type: str = "", entity_id: object = "") -> None:
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, client_id=client_id, action=action, entity_type=entity_type, entity_id=str(entity_id)))

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Client, User
from ..security import audit, create_token, current_user, verify_password
from ..serializers import me_out, user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def _me(db: Session, user: User) -> dict:
    client = db.get(Client, user.client_id) if user.client_id else None
    return me_out(user, client.company_name if client else None)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if not user or user.status != "active" or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    audit(db, user, "signed in", entity_type="user", entity_id=user.id)
    db.commit()
    return {"access_token": create_token(user), "token_type": "bearer", "user": _me(db, user)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _me(db, user)


@router.get("/users")
def users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Staff directory for task assignment."""
    rows = db.scalars(select(User).where(User.tenant_id == user.tenant_id, User.role != "client").order_by(User.name))
    return [user_out(u) for u in rows]

"""User and role administration (Admins: settings.edit). Roles live in the `roles` table per tenant."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, User
from ..security import ALL_ACTIONS, ALL_SECTIONS, audit, get_client, hash_password, require, require_section
from ..serializers import user_out

router = APIRouter(prefix="/api", tags=["users"])

MIN_PASSWORD = 8


def _roles(db: Session, tenant_id: int) -> dict[str, Role]:
    return {r.name: r for r in db.scalars(select(Role).where(Role.tenant_id == tenant_id).order_by(Role.id))}


def _out(u: User, roles: dict[str, Role]) -> dict:
    u.role_label = roles[u.role].label if u.role in roles else u.role
    return user_out(u)


# ---------- users ----------

@router.get("/users")
def list_users(user: User = Depends(require_section("settings")), db: Session = Depends(get_db)):
    roles = _roles(db, user.tenant_id)
    return [_out(u, roles) for u in db.scalars(select(User).where(User.tenant_id == user.tenant_id).order_by(User.name))]


class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=MIN_PASSWORD, max_length=128)
    role: str
    client_id: int | None = None  # required for the client-portal role


def _check_role_and_client(db: Session, admin: User, role: str, client_id: int | None) -> None:
    if role not in _roles(db, admin.tenant_id):
        raise HTTPException(422, f"Unknown role “{role}”")
    if role == "client" and client_id is None:
        raise HTTPException(422, "Client-portal users must be linked to a client")
    if role != "client" and client_id is not None:
        raise HTTPException(422, "Only client-portal users can be linked to a client")
    if client_id is not None:
        get_client(db, admin, client_id)


@router.post("/users", status_code=201)
def create_user(body: UserIn, user: User = Depends(require("settings.edit")), db: Session = Depends(get_db)):
    _check_role_and_client(db, user, body.role, body.client_id)
    email = body.email.strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "A user with that email already exists")
    u = User(tenant_id=user.tenant_id, name=body.name.strip(), email=email, password_hash=hash_password(body.password), role=body.role, client_id=body.client_id)
    db.add(u)
    db.flush()
    audit(db, user, f"created user {email} ({body.role})", entity_type="user", entity_id=u.id)
    db.commit()
    return _out(u, _roles(db, user.tenant_id))


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = None
    client_id: int | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    password: str | None = Field(default=None, min_length=MIN_PASSWORD, max_length=128)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, user: User = Depends(require("settings.edit")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or u.tenant_id != user.tenant_id:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if u.id == user.id and (changes.get("status") == "disabled" or ("role" in changes and changes["role"] != u.role)):
        raise HTTPException(409, "You can't disable yourself or change your own role — ask another admin")
    if "role" in changes or "client_id" in changes:
        _check_role_and_client(db, user, changes.get("role", u.role), changes.get("client_id", u.client_id if "role" not in changes or changes["role"] == "client" else None))
    for k, v in changes.items():
        if k == "password":
            u.password_hash = hash_password(v)
        elif k == "role":
            u.role = v
            if v != "client":
                u.client_id = None
        else:
            setattr(u, k, v)
    audit(db, user, f"updated user {u.email}: {', '.join('password' if k == 'password' else f'{k}={v}' for k, v in changes.items())}",
          entity_type="user", entity_id=u.id)
    db.commit()
    return _out(u, _roles(db, user.tenant_id))


# ---------- roles ----------

@router.get("/roles")
def list_roles(user: User = Depends(require_section("settings")), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(User.role, func.count()).where(User.tenant_id == user.tenant_id).group_by(User.role)).all())
    return {
        "sections": ALL_SECTIONS,
        "permissions": ALL_ACTIONS,
        "roles": [{"name": r.name, "label": r.label, "sections": r.sections, "permissions": r.permissions, "users": counts.get(r.name, 0)}
                  for r in _roles(db, user.tenant_id).values()],
    }


class RolePatch(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=60)
    sections: list[str] | None = None
    permissions: list[str] | None = None


@router.patch("/roles/{name}")
def update_role(name: str, body: RolePatch, user: User = Depends(require("settings.edit")), db: Session = Depends(get_db)):
    role = _roles(db, user.tenant_id).get(name)
    if not role:
        raise HTTPException(404, "Role not found")
    if body.sections is not None:
        bad = set(body.sections) - set(ALL_SECTIONS)
        if bad:
            raise HTTPException(422, f"Unknown sections: {', '.join(sorted(bad))}")
        role.sections = [s for s in ALL_SECTIONS if s in body.sections]
    if body.permissions is not None:
        bad = set(body.permissions) - set(ALL_ACTIONS)
        if bad:
            raise HTTPException(422, f"Unknown permissions: {', '.join(sorted(bad))}")
        role.permissions = [a for a in ALL_ACTIONS if a in body.permissions]
    if body.label is not None:
        role.label = body.label.strip()
    if name == "admin" and ("settings" not in role.sections or "settings.edit" not in role.permissions):
        raise HTTPException(409, "The Admin role must keep Settings access and the settings.edit permission, or nobody could manage users")
    audit(db, user, f"updated role {name}", entity_type="role", entity_id=role.id)
    db.commit()
    return {"name": role.name, "label": role.label, "sections": role.sections, "permissions": role.permissions}

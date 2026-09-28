from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, Task, User
from ..security import audit, get_client, require_section, scoped_ids
from ..serializers import audit_out, task_out
from .common import client_names, user_names

router = APIRouter(prefix="/api", tags=["tasks"])

Status = Literal["todo", "in_progress", "review", "done"]
Priority = Literal["low", "medium", "high"]


@router.get("/tasks")
def list_tasks(client_id: int | None = None, mine: bool = False, user: User = Depends(require_section("tasks")), db: Session = Depends(get_db)):
    ids = scoped_ids(db, user, client_id)
    q = select(Task).where(Task.tenant_id == user.tenant_id, Task.client_id.in_(ids)).order_by(Task.due_date)
    if mine:
        q = q.where(Task.assigned_to == user.id)
    names, users = client_names(db, user.tenant_id), user_names(db, user.tenant_id)
    return [task_out(t, names.get(t.client_id), users.get(t.assigned_to)) for t in db.scalars(q)]


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    client_id: int
    assigned_to: int
    priority: Priority = "medium"
    due_date: date | None = None


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, user: User = Depends(require_section("tasks")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    assignee = db.get(User, body.assigned_to)
    if not assignee or assignee.tenant_id != user.tenant_id:
        raise HTTPException(422, "Unknown assignee")
    t = Task(tenant_id=user.tenant_id, client_id=c.id, assigned_to=assignee.id, title=body.title.strip(), priority=body.priority, due_date=body.due_date)
    db.add(t)
    db.flush()
    audit(db, user, f'created task "{t.title}"', client_id=c.id, entity_type="task", entity_id=t.id)
    db.commit()
    return task_out(t, c.company_name, assignee.name)


class TaskPatch(BaseModel):
    status: Status | None = None
    priority: Priority | None = None
    assigned_to: int | None = None
    due_date: date | None = None


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch, user: User = Depends(require_section("tasks")), db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t or t.tenant_id != user.tenant_id:
        raise HTTPException(404, "Task not found")
    get_client(db, user, t.client_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(t, k, v)
    audit(db, user, f'task "{t.title}" → {t.status.replace("_", " ")}' if "status" in changes else f'updated task "{t.title}"',
          client_id=t.client_id, entity_type="task", entity_id=t.id)
    db.commit()
    return task_out(t, client_names(db, user.tenant_id).get(t.client_id), user_names(db, user.tenant_id).get(t.assigned_to))


@router.get("/audit")
def audit_trail(client_id: int | None = None, limit: int = 50, user: User = Depends(require_section("tasks")), db: Session = Depends(get_db)):
    q = select(AuditLog).where(AuditLog.tenant_id == user.tenant_id).order_by(AuditLog.id.desc()).limit(min(limit, 200))
    if client_id is not None:
        q = q.where(AuditLog.client_id == get_client(db, user, client_id).id)
    names, users = client_names(db, user.tenant_id), user_names(db, user.tenant_id)
    return [audit_out(a, users.get(a.user_id), names.get(a.client_id)) for a in db.scalars(q)]

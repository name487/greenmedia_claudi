from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, User


def client_names(db: Session, tenant_id: int) -> dict[int, str]:
    return dict(db.execute(select(Client.id, Client.company_name).where(Client.tenant_id == tenant_id)).all())


def user_names(db: Session, tenant_id: int) -> dict[int, str]:
    return dict(db.execute(select(User.id, User.name).where(User.tenant_id == tenant_id)).all())

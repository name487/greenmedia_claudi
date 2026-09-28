from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..metrics import compare, periods, series, totals
from ..models import Client, User
from ..security import require_section, scoped_ids

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def analytics(client_id: int | None = None, days: int = 30, user: User = Depends(require_section("analytics")), db: Session = Depends(get_db)):
    if days not in (7, 30, 45):
        raise HTTPException(422, "days must be 7, 30 or 45")
    ids = scoped_ids(db, user, client_id)
    (cs, ce), (ps, pe) = periods(days)
    out = {"days": days, "totals": compare(totals(db, ids, cs, ce), totals(db, ids, ps, pe)), "series": series(db, ids, cs, ce)}
    if client_id is None and len(ids) > 1:
        names = dict(db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids))).all())
        top = sorted(({"client_id": i, "client_name": names[i], "leads": totals(db, [i], cs, ce)["leads"]} for i in ids), key=lambda x: -x["leads"])
        out["top_clients"] = top[:10]
    return out

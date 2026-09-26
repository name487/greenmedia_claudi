from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..metrics import compare, periods, series, totals
from ..models import Client, Keyword, Task, User
from ..security import audit, get_client, require_section, scoped_ids
from ..serializers import keyword_out, task_out
from .common import user_names

router = APIRouter(prefix="/api/seo", tags=["seo"])


@router.get("")
def seo(client_id: int | None = None, sort: Literal["change", "rank", "volume"] = "change",
        user: User = Depends(require_section("seo")), db: Session = Depends(get_db)):
    ids = scoped_ids(db, user, client_id)
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids))).all())
    kws = list(db.scalars(select(Keyword).where(Keyword.client_id.in_(ids))))
    key = {"rank": lambda k: k.current_rank, "volume": lambda k: -k.volume, "change": lambda k: -(k.previous_rank - k.current_rank)}[sort]
    kws.sort(key=key)
    (cs, ce), (ps, pe) = periods(30)
    (s90, _), _ = periods(90)
    seo_user_ids = [u for u, in db.execute(select(User.id).where(User.tenant_id == user.tenant_id, User.role == "seo"))]
    users = user_names(db, user.tenant_id)
    tasks = db.scalars(select(Task).where(Task.client_id.in_(ids), Task.assigned_to.in_(seo_user_ids), Task.status != "done"))
    cmp = compare(totals(db, ids, cs, ce), totals(db, ids, ps, pe))
    return {
        "summary": {
            "tracked": len(kws), "top10": sum(k.current_rank <= 10 for k in kws), "improved": sum(k.current_rank < k.previous_rank for k in kws),
            "organic_sessions": cmp["organic_sessions"], "search_clicks": cmp["web_clicks"],
        },
        "traffic": [{"date": d["date"], "organic_sessions": d["organic_sessions"], "web_clicks": d["web_clicks"]} for d in series(db, ids, s90, ce)],
        "keywords": [keyword_out(k, names[k.client_id]) for k in kws],
        "tasks": [task_out(t, names.get(t.client_id), users.get(t.assigned_to)) for t in tasks],
    }


class KeywordIn(BaseModel):
    client_id: int
    keyword: str = Field(min_length=2, max_length=200)
    target_url: str | None = None


@router.post("/keywords", status_code=201)
def add_keyword(body: KeywordIn, user: User = Depends(require_section("seo")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    # Rank is filled in by the nightly rank-tracker job; start unranked (100) until the first check.
    k = Keyword(tenant_id=user.tenant_id, client_id=c.id, keyword=body.keyword.strip(), target_url=body.target_url or c.website, location=c.city,
                current_rank=100, previous_rank=100, volume=0)
    db.add(k)
    db.flush()
    audit(db, user, f'tracking keyword "{k.keyword}"', client_id=c.id, entity_type="seo_keyword", entity_id=k.id)
    db.commit()
    return keyword_out(k, c.company_name)

"""The owner's monthly report (app → Report): the data for the screen, and the PDF behind a short-lived signed link
(the phone's browser or download manager can't send our bearer token)."""

import re
from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import home, report_pdf
from .. import monthly_report as mr
from .. import score as scoring
from ..config import settings
from ..db import get_db
from ..models import Client, User
from ..security import get_client, require_section

router = APIRouter(prefix="/api/clients", tags=["monthly report"])
LINK_MINUTES = 15


def _month(month: str | None) -> date:
    if not month:
        return mr.default_month()
    try:
        m = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(422, "month must look like 2026-09")
    if m > mr.month_start(date.today()):
        raise HTTPException(422, "That month hasn't started yet")
    return m


@router.get("/{client_id}/monthly-report")
def report(client_id: int, month: str | None = None, user: User = Depends(require_section("reports")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    return mr.build(db, c, _month(month))


@router.post("/{client_id}/monthly-report/link")
def report_link(client_id: int, request: Request, month: str | None = None, user: User = Depends(require_section("reports")),
                db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    m = _month(month)
    exp = datetime.now(timezone.utc) + timedelta(minutes=LINK_MINUTES)
    token = jwt.encode({"purpose": "monthly_report", "cid": c.id, "tid": c.tenant_id, "month": m.isoformat()[:7], "exp": exp},
                       settings.jwt_secret, algorithm="HS256")
    url = request.url_for("monthly_report_pdf", client_id=c.id).include_query_params(t=token)
    return {"url": str(url), "expires_at": exp.isoformat(), "filename": _filename(c, m)}


def _filename(c: Client, m: date) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", c.company_name.lower()).strip("_")
    return f"report_{slug}_{m.isoformat()[:7]}.pdf"


@router.get("/{client_id}/monthly-report.pdf", name="monthly_report_pdf")
def report_pdf_file(client_id: int, t: str, db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(t, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "This report link has expired — download the report again from the app")
    c = db.get(Client, client_id)
    if claims.get("purpose") != "monthly_report" or claims.get("cid") != client_id or not c or c.tenant_id != claims.get("tid"):
        raise HTTPException(401, "This report link is not valid")
    m = date.fromisoformat(f"{claims['month']}-01")
    data = mr.build(db, c, m)
    d = scoring.build(db, c)
    track = home.tracker(db, c, date.today())
    actions = home.growth_actions(c, d, track, len(home.tracked(db, c)))
    pdf = report_pdf.render(data, mr.pending_counts(db, c), actions)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{_filename(c, m)}"'})

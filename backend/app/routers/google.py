from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from urllib.parse import quote

from ..config import settings
from ..db import get_db
from ..google import api, service
from ..google.crypto import decrypt, encrypt
from ..models import Client, GmbAccount, GoogleConnection, User
from ..security import audit, get_client, require

router = APIRouter(prefix="/api/google", tags=["google"])


def _require_configured():
    if not settings.google_configured:
        raise HTTPException(503, "Google is not configured on the server: set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI.")


def _conn_out(c: GoogleConnection, linked: int) -> dict:
    return {"id": c.id, "email": c.email, "status": c.status, "last_error": c.last_error, "linked_locations": linked, "created_at": c.created_at.isoformat()}


@router.get("/status")
def status(user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    conns = list(db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == user.tenant_id).order_by(GoogleConnection.id)))
    linked = list(db.scalars(select(GmbAccount).where(GmbAccount.tenant_id == user.tenant_id, GmbAccount.connection_id.is_not(None))))
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.tenant_id == user.tenant_id)).all())
    return {
        "configured": settings.google_configured,
        "redirect_uri": settings.google_redirect_uri,
        "web_app_url": settings.web_app_url,  # where Google's return lands; must be the address people use for the web app
        "connections": [_conn_out(c, sum(g.connection_id == c.id for g in linked)) for c in conns],
        "linked": [{"client_id": g.client_id, "client_name": names.get(g.client_id), "title": g.title, "location": g.location_id, "status": g.status,
                    "last_sync": g.last_sync.isoformat() if g.last_sync else None, "last_error": g.last_error, "connection_id": g.connection_id} for g in linked],
    }


@router.post("/connect")
def connect(user: User = Depends(require("client.edit"))):
    """Returns Google's consent URL. The browser goes there, the user signs in with the Google account that
    manages the Business Profiles, and Google redirects back to /api/google/callback."""
    _require_configured()
    state = jwt.encode({"tid": user.tenant_id, "uid": user.id, "purpose": "google_oauth", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
                       settings.jwt_secret, algorithm="HS256")
    return {"auth_url": api.auth_url(state)}


def _back(result: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.web_app_url}/gmb/google/?google={quote(result)}", status_code=303)


@router.get("/callback", include_in_schema=False)
def callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    if error:
        return _back(f"error:{error}")
    try:
        st = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
        assert st.get("purpose") == "google_oauth"
    except (jwt.PyJWTError, AssertionError):
        return _back("error:invalid_or_expired_state")
    user = db.get(User, st["uid"])
    if not user or user.tenant_id != st["tid"]:
        return _back("error:unknown_user")
    try:
        tokens = api.exchange_code(code)
        email = api.userinfo_email(tokens["access_token"])
    except api.GoogleApiError as e:
        return _back(f"error:{e}")
    refresh = tokens.get("refresh_token")
    if not refresh:
        return _back("error:google_returned_no_refresh_token")
    conn = db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == user.tenant_id, GoogleConnection.email == email))
    if conn is None:
        conn = GoogleConnection(tenant_id=user.tenant_id, email=email, refresh_token_enc="", connected_by=user.id)
        db.add(conn)
    conn.refresh_token_enc, conn.scopes, conn.status, conn.last_error = encrypt(refresh), tokens.get("scope", ""), "active", ""
    db.flush()
    audit(db, user, f"connected Google account {email}", entity_type="google_connection", entity_id=conn.id)
    db.commit()
    return _back(f"connected:{email}")


def _conn(db: Session, user: User, conn_id: int) -> GoogleConnection:
    c = db.get(GoogleConnection, conn_id)
    if not c or c.tenant_id != user.tenant_id:
        raise HTTPException(404, "Google connection not found")
    return c


@router.get("/locations")
def locations(user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Every Business Profile location the connected Google accounts can manage, with the client it is linked to."""
    _require_configured()
    linked = {g.location_id: g.client_id for g in db.scalars(select(GmbAccount).where(GmbAccount.tenant_id == user.tenant_id, GmbAccount.connection_id.is_not(None)))}
    out, errors = [], []
    for conn in db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == user.tenant_id, GoogleConnection.status == "active")):
        try:
            for loc in service.list_locations(conn):
                out.append({**loc, "email": conn.email, "linked_client_id": linked.get(loc["location"])})
        except api.GoogleApiError as e:
            conn.last_error = str(e)
            errors.append({"email": conn.email, "error": str(e)})
    db.commit()
    return {"locations": out, "errors": errors}


class LinkIn(BaseModel):
    client_id: int
    connection_id: int
    account: str
    location: str
    title: str = ""
    sync_now: bool = True


@router.post("/link")
def link(body: LinkIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    conn = _conn(db, user, body.connection_id)
    other = db.scalar(select(GmbAccount).where(GmbAccount.tenant_id == user.tenant_id, GmbAccount.location_id == body.location,
                                               GmbAccount.connection_id.is_not(None), GmbAccount.client_id != c.id))
    if other:
        raise HTTPException(409, "That location is already linked to another client")
    service.link(db, c, conn, body.account, body.location, body.title)
    audit(db, user, f"linked Google Business Profile “{body.title or body.location}”", client_id=c.id, entity_type="gmb_account", entity_id=c.gmb.id)
    result: dict = {"linked": True}
    if body.sync_now:
        try:
            result["sync"] = service.sync_client(db, c)
        except api.GoogleApiError as e:
            result["sync_error"] = str(e)
    db.commit()
    return result


class UnlinkIn(BaseModel):
    client_id: int


@router.post("/unlink")
def unlink(body: UnlinkIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, body.client_id)
    if c.gmb and c.gmb.is_live:
        c.gmb.connection_id, c.gmb.status = None, "disconnected"
        audit(db, user, "unlinked Google Business Profile", client_id=c.id, entity_type="gmb_account", entity_id=c.gmb.id)
        db.commit()
    return {"linked": False}


@router.delete("/connections/{conn_id}")
def disconnect(conn_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    conn = _conn(db, user, conn_id)
    try:  # best effort: also revoke on Google's side
        api.http.post("https://oauth2.googleapis.com/revoke", data={"token": decrypt(conn.refresh_token_enc)})
    except Exception:  # noqa: BLE001
        pass
    for g in db.scalars(select(GmbAccount).where(GmbAccount.connection_id == conn.id)):
        g.connection_id, g.status = None, "disconnected"
    audit(db, user, f"disconnected Google account {conn.email}", entity_type="google_connection", entity_id=conn.id)
    db.delete(conn)
    db.commit()
    return {"ok": True}

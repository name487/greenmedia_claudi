"""Google Business Profile: OAuth connect/callback, encrypted token storage, locations, link/unlink, diagnostics.

Two ways to grant access, both through Google's consent screen (we never see a password):
- Agency connection: a Google account that manages many profiles (e.g. the agency's SEO account). Stored in
  google_connections; any of its locations can be linked to any client.
- Per-client sign-in: the client's own Google account, started from the Client Workspace. Its tokens are
  stored encrypted on that client's gmb_accounts row and only serve that client.
"""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .. import review_queue
from ..google import api, service, tokens
from ..google.crypto import decrypt
from ..models import Client, GmbAccount, GoogleConnection, User
from ..security import audit, can, current_user, get_client, load_role, require
from ..serializers import gmb_out

router = APIRouter(prefix="/api/google", tags=["google"])
client_router = APIRouter(prefix="/api/clients/{client_id}/google", tags=["google"])

MANAGE_SCOPE = "https://www.googleapis.com/auth/business.manage"


def _require_configured():
    if not settings.google_configured:
        raise HTTPException(503, "Google is not configured on the server: set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI.")


def _conn_out(c: GoogleConnection, linked: int) -> dict:
    return {"id": c.id, "email": c.email, "status": c.status, "last_error": c.last_error, "linked_locations": linked,
            "created_at": c.created_at.isoformat(), "access_token_expires_at": tokens.expires_at_iso(c)}


def _live(db: Session, tenant_id: int) -> list[GmbAccount]:
    rows = db.scalars(select(GmbAccount).where(GmbAccount.tenant_id == tenant_id, GmbAccount.google_account != ""))
    return [g for g in rows if g.is_live]


@router.get("/status")
def status(user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    conns = list(db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == user.tenant_id).order_by(GoogleConnection.id)))
    linked = _live(db, user.tenant_id)
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.tenant_id == user.tenant_id)).all())
    return {
        "configured": settings.google_configured,
        "redirect_uri": settings.google_redirect_uri,
        "web_app_url": settings.web_app_url,  # where Google's return lands; must be the address people use for the web app
        "project_number": _project_number(),
        "connections": [_conn_out(c, sum(g.connection_id == c.id for g in linked)) for c in conns],
        "linked": [{"client_id": g.client_id, "client_name": names.get(g.client_id), "title": g.title, "location": g.location_id, "status": g.status,
                    "last_sync": g.last_sync.isoformat() if g.last_sync else None, "last_error": g.last_error, "connection_id": g.connection_id,
                    "google_email": g.connection.email if g.connection else g.google_email, "via": "agency" if g.connection_id else "client"}
                   for g in linked],
    }


# ---------- OAuth ----------

def _state(user: User, client_id: int | None) -> str:
    payload = {"tid": user.tenant_id, "uid": user.id, "purpose": "google_oauth", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}
    if client_id is not None:
        payload["cid"] = client_id
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@router.post("/connect")
def connect(user: User = Depends(require("client.edit"))):
    """Agency connection. Returns Google's consent URL; the browser goes there, the user signs in with the Google
    account that manages the Business Profiles, and Google redirects back to /api/google/callback."""
    _require_configured()
    return {"auth_url": api.auth_url(_state(user, None))}


@client_router.post("/connect")
def client_connect(client_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Per-client connection: same consent screen, but the tokens are saved on this client's gmb_accounts row."""
    _require_configured()
    get_client(db, user, client_id)
    return {"auth_url": api.auth_url(_state(user, client_id))}


def _back(result: str, client_id: int | None = None) -> RedirectResponse:
    page = f"/clients/{client_id}/" if client_id else "/gmb/google/"
    return RedirectResponse(f"{settings.web_app_url}{page}?google={quote(result)}", status_code=303)


@router.get("/callback", include_in_schema=False)
def callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    try:
        st = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
        assert st.get("purpose") == "google_oauth"
    except (jwt.PyJWTError, AssertionError):
        return _back("error:invalid_or_expired_state")
    cid = st.get("cid")
    if error:
        return _back(f"error:{error}", cid)
    user = db.get(User, st["uid"])
    if not user or user.tenant_id != st["tid"] or user.status != "active" or not can(load_role(db, user), "client.edit"):
        return _back("error:not_allowed", cid)  # disabled, or lost the permission since starting
    try:
        granted = api.exchange_code(code)
        email = api.userinfo_email(granted["access_token"])
    except api.GoogleApiError as e:
        return _back(f"error:{e}", cid)
    if MANAGE_SCOPE not in granted.get("scope", "").split():
        # Google's consent screen lets people untick permissions; without this one nothing works.
        return _back("error:the Business Profile permission was not granted — connect again and tick “See, edit, create and delete your Google business listings”", cid)
    if not granted.get("refresh_token"):
        return _back("error:google_returned_no_refresh_token", cid)
    if cid is not None:
        return _client_callback(db, user, cid, email, granted)
    conn = db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == user.tenant_id, GoogleConnection.email == email))
    if conn is None:
        conn = GoogleConnection(tenant_id=user.tenant_id, email=email, refresh_token_enc="", connected_by=user.id)
        db.add(conn)
    tokens.store(conn, granted)
    conn.scopes, conn.status, conn.last_error = granted.get("scope", ""), "active", ""
    db.flush()
    audit(db, user, f"connected Google account {email}", entity_type="google_connection", entity_id=conn.id)
    db.commit()
    return _back(f"connected:{email}")


def _client_callback(db: Session, user: User, cid: int, email: str, granted: dict) -> RedirectResponse:
    try:
        client = get_client(db, user, cid)
    except HTTPException:
        return _back("error:client_not_found")
    gmb = service.ensure_gmb(client)
    if gmb.connection_id is None and gmb.is_live and gmb.google_email and gmb.google_email != email:
        # A different Google account than the one the live location was linked through: unlink, it may not manage it.
        service.unlink(gmb)
    tokens.store(gmb, granted)
    gmb.google_email, gmb.scopes, gmb.token_status, gmb.last_error = email, granted.get("scope", ""), "active", ""
    db.flush()
    audit(db, user, f"connected Google account {email}", client_id=client.id, entity_type="gmb_account", entity_id=gmb.id)
    result = f"reconnected:{email}" if gmb.is_live else f"connected:{email}"
    if not gmb.is_live:
        # Most businesses have exactly one profile: link it straight away so the workspace shows real data.
        try:
            free = [x for x in service.list_locations(gmb) if _owner(db, user, x["location"], client.id) is None]
            if len(free) == 1:
                service.link(db, client, None, free[0])
                audit(db, user, f"linked Google Business Profile “{free[0]['title']}”", client_id=client.id, entity_type="gmb_account", entity_id=gmb.id)
                result = f"linked:{free[0]['title'] or free[0]['location']}"
                try:
                    review_queue.sync_live(db, client)
                except api.GoogleApiError:
                    pass  # recorded on gmb.last_error and shown on the panel
        except api.GoogleApiError as e:
            gmb.last_error = str(e)
    db.commit()
    return _back(result, cid)


# ---------- locations & linking ----------

def _conn(db: Session, user: User, conn_id: int) -> GoogleConnection:
    c = db.get(GoogleConnection, conn_id)
    if not c or c.tenant_id != user.tenant_id:
        raise HTTPException(404, "Google connection not found")
    return c


def _owner(db: Session, user: User, location: str, other_than: int | None = None) -> int | None:
    """The client a location is already linked to (live), if any."""
    for g in db.scalars(select(GmbAccount).where(GmbAccount.tenant_id == user.tenant_id, GmbAccount.location_id == location)):
        if g.is_live and g.client_id != other_than:
            return g.client_id
    return None


def _agency_locations(db: Session, user: User) -> tuple[list[dict], list[dict]]:
    out, errors = [], []
    for conn in db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == user.tenant_id, GoogleConnection.status == "active")):
        try:
            out += [{**loc, "email": conn.email} for loc in service.list_locations(conn)]
        except api.GoogleApiError as e:
            conn.last_error = str(e)
            errors.append({"email": conn.email, "error": str(e)})
    return out, errors


def _with_owner(db: Session, user: User, locs: list[dict]) -> list[dict]:
    linked = {g.location_id: g.client_id for g in _live(db, user.tenant_id)}
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.tenant_id == user.tenant_id)).all())
    return [{**x, "linked_client_id": linked.get(x["location"]), "linked_client_name": names.get(linked.get(x["location"]))} for x in locs]


@router.get("/locations")
def locations(user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Every Business Profile location the agency's connected Google accounts can manage, with the client it is linked to."""
    _require_configured()
    out, errors = _agency_locations(db, user)
    db.commit()  # refreshed access tokens and errors
    return {"locations": _with_owner(db, user, out), "errors": errors}


def _do_link(db: Session, user: User, c: Client, conn_id: int | None, account: str, location: str, sync_now: bool) -> dict:
    holder = _conn(db, user, conn_id) if conn_id is not None else c.gmb
    if holder is None or (conn_id is None and not c.gmb.has_own_token):
        raise HTTPException(400, "Connect the client's Google account first, or pick a location from an agency connection")
    if _owner(db, user, location, other_than=c.id):
        raise HTTPException(409, "That location is already linked to another client")
    try:
        loc = next((x for x in service.list_locations(holder) if x["account"] == account and x["location"] == location), None)
    except api.GoogleApiError as e:
        db.commit()
        raise HTTPException(502, str(e)) from e
    if loc is None:
        raise HTTPException(404, "That Google account does not manage this location")
    service.link(db, c, holder if conn_id is not None else None, loc)
    audit(db, user, f"linked Google Business Profile “{loc['title'] or location}”", client_id=c.id, entity_type="gmb_account", entity_id=c.gmb.id)
    result: dict = {"linked": True, "gmb": gmb_out(c.gmb)}
    if sync_now:
        try:
            result["sync"] = review_queue.sync_live(db, c)
        except api.GoogleApiError as e:
            result["sync_error"] = str(e)
        result["gmb"] = gmb_out(c.gmb)
    db.commit()
    return result


class LinkIn(BaseModel):
    client_id: int
    connection_id: int
    account: str
    location: str
    title: str = ""  # ignored: the title is read from Google
    sync_now: bool = True


@router.post("/link")
def link(body: LinkIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    return _do_link(db, user, get_client(db, user, body.client_id), body.connection_id, body.account, body.location, body.sync_now)


class UnlinkIn(BaseModel):
    client_id: int


def _do_unlink(db: Session, user: User, c: Client) -> dict:
    if c.gmb and c.gmb.is_live:
        service.unlink(c.gmb)
        audit(db, user, "unlinked Google Business Profile", client_id=c.id, entity_type="gmb_account", entity_id=c.gmb.id)
        db.commit()
    return {"linked": False}


@router.post("/unlink")
def unlink(body: UnlinkIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    return _do_unlink(db, user, get_client(db, user, body.client_id))


def _shared_grant(db: Session, tenant_id: int, email: str, *, conn_id: int | None = None, gmb_id: int | None = None) -> bool:
    """Revoking a token revokes the whole Google grant for that account, so only revoke when no other
    connection or client in this workspace signed in with the same Google account."""
    if db.scalar(select(GoogleConnection.id).where(GoogleConnection.tenant_id == tenant_id, GoogleConnection.email == email,
                                                   GoogleConnection.id != (conn_id or 0)).limit(1)):
        return True
    return bool(db.scalar(select(GmbAccount.id).where(GmbAccount.tenant_id == tenant_id, GmbAccount.google_email == email,
                                                      GmbAccount.refresh_token_enc != "", GmbAccount.id != (gmb_id or 0)).limit(1)))


@router.delete("/connections/{conn_id}")
def disconnect(conn_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    conn = _conn(db, user, conn_id)
    if not _shared_grant(db, user.tenant_id, conn.email, conn_id=conn.id):
        try:
            api.revoke(decrypt(conn.refresh_token_enc))
        except ValueError:
            pass
    for g in db.scalars(select(GmbAccount).where(GmbAccount.connection_id == conn.id)):
        service.unlink(g)
    audit(db, user, f"disconnected Google account {conn.email}", entity_type="google_connection", entity_id=conn.id)
    db.delete(conn)
    db.commit()
    return {"ok": True}


# ---------- per client ----------

@client_router.get("")
def client_profile(client_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The client's Google Business Profile: who it's connected through, the linked location, token state."""
    c = get_client(db, user, client_id)
    return {"configured": settings.google_configured, "can_manage": can(user, "client.edit"), "profile": gmb_out(c.gmb) if c.gmb else None}


@client_router.get("/locations")
def client_locations(client_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Locations this client can be linked to: those its own Google sign-in manages, then the agency connections'."""
    _require_configured()
    c = get_client(db, user, client_id)
    out, errors = [], []
    if c.gmb and c.gmb.has_own_token:
        try:
            out += [{**loc, "email": c.gmb.google_email} for loc in service.list_locations(c.gmb)]
        except api.GoogleApiError as e:
            c.gmb.last_error = str(e)
            errors.append({"email": c.gmb.google_email, "error": str(e)})
    agency, agency_errors = _agency_locations(db, user)
    db.commit()
    return {"locations": _with_owner(db, user, out + agency), "errors": errors + agency_errors}


class ClientLinkIn(BaseModel):
    connection_id: int | None = None  # None = the client's own Google sign-in
    account: str
    location: str
    sync_now: bool = True


@client_router.post("/link")
def client_link(client_id: int, body: ClientLinkIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    return _do_link(db, user, get_client(db, user, client_id), body.connection_id, body.account, body.location, body.sync_now)


@client_router.post("/unlink")
def client_unlink(client_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    return _do_unlink(db, user, get_client(db, user, client_id))


@client_router.post("/refresh")
def client_refresh(client_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Get a new access token now (normally this happens automatically shortly before expiry). Doubles as a
    "test connection": it fails if the client revoked access."""
    _require_configured()
    c = get_client(db, user, client_id)
    if not c.gmb or (c.gmb.connection_id is None and not c.gmb.refresh_token_enc):
        raise HTTPException(400, "Google is not connected for this client")
    holder = service.source(c.gmb)
    try:
        tokens.access_token(holder, force_refresh=True)
    except api.GoogleApiError as e:
        if e.auth_failed:
            service.mark_revoked(holder, e)
        db.commit()
        raise HTTPException(502, str(e)) from e
    db.commit()
    return {"ok": True, "gmb": gmb_out(c.gmb), "access_token_expires_at": tokens.expires_at_iso(holder)}


@client_router.delete("")
def client_disconnect(client_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Remove the client's own Google sign-in (revoking it at Google) and unlink a location that depended on it."""
    c = get_client(db, user, client_id)
    g = c.gmb
    if not g or not g.refresh_token_enc:
        return {"ok": True}
    email = g.google_email
    if not _shared_grant(db, user.tenant_id, email, gmb_id=g.id):
        try:
            api.revoke(decrypt(g.refresh_token_enc))
        except ValueError:
            pass
    if g.is_live and g.connection_id is None:
        service.unlink(g)
    g.refresh_token_enc, g.google_email, g.scopes, g.token_status = "", "", "", ""
    tokens.clear(g)
    audit(db, user, f"disconnected Google account {email}", client_id=c.id, entity_type="gmb_account", entity_id=g.id)
    db.commit()
    return {"ok": True}


# ---------- Google Cloud project diagnostics ----------

APIS = [
    ("mybusinessaccountmanagement.googleapis.com", "My Business Account Management API", "lists the Google accounts/business groups"),
    ("mybusinessbusinessinformation.googleapis.com", "My Business Business Information API", "lists locations (title, address, Maps link)"),
    ("mybusiness.googleapis.com", "Google My Business API (v4)", "reviews, review replies, posts"),
    ("businessprofileperformance.googleapis.com", "Business Profile Performance API", "views, calls, directions, website clicks"),
]


def _project_number() -> str | None:
    m = re.match(r"^(\d+)-", settings.google_client_id or "")
    return m.group(1) if m else None


def _classify(e: api.GoogleApiError) -> tuple[str, str]:
    msg = str(e)
    low = msg.lower()
    if "service_disabled" in low or "has not been used in project" in low or "is disabled" in low:
        return "disabled", "This API is not enabled in the Google Cloud project — open the link and press Enable (it can take a few minutes)."
    if e.status == 429 or "quota" in low:
        return "quota", ("Quota is 0 — Google has not approved Business Profile API access for this project yet. "
                         "Submit the access request form (see README) and wait for approval email.")
    if e.auth_failed:
        return "auth", "The stored Google sign-in was revoked or expired — reconnect Google."
    if e.status == 403:
        return "forbidden", "Google refused access — the signed-in account may not manage this profile."
    return "error", msg


@router.get("/diagnostics")
def diagnostics(live: bool = False, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Checks the Google Cloud project setup. With live=1 it also calls each API once with a stored sign-in and
    reports which ones work, which are disabled and which still have zero quota."""
    num = _project_number()
    proj = f"?project={num}" if num else ""
    checks: list[dict] = []

    def add(key: str, ok: bool | None, label: str, detail: str = "", fix: str = ""):
        checks.append({"key": key, "status": "ok" if ok else ("warn" if ok is None else "fail"), "label": label, "detail": detail, "fix_url": fix})

    cid = settings.google_client_id or ""
    add("client_id", cid.endswith(".apps.googleusercontent.com"), "OAuth client ID (GOOGLE_CLIENT_ID)",
        f"Project number {num}" if num else "Not set, or not a Web OAuth client ID", f"https://console.cloud.google.com/apis/credentials{proj}")
    add("client_secret", bool(settings.google_client_secret), "OAuth client secret (GOOGLE_CLIENT_SECRET)",
        "Set" if settings.google_client_secret else "Not set", f"https://console.cloud.google.com/apis/credentials{proj}")
    ru = urlparse(settings.google_redirect_uri)
    add("redirect_uri", ru.path == "/api/google/callback" and ru.scheme in ("http", "https"), "Redirect URI (GOOGLE_REDIRECT_URI)",
        f"{settings.google_redirect_uri} — add exactly this under “Authorized redirect URIs” of the OAuth client",
        f"https://console.cloud.google.com/apis/credentials{proj}")
    web = urlparse(settings.web_app_url)
    add("hosts", ru.hostname == web.hostname, "Same host for API and web app",
        f"API {ru.hostname}, web app {web.hostname}" + ("" if ru.hostname == web.hostname else " — use the same host (e.g. 127.0.0.1 for both) so the login cookie survives the redirect"))
    add("encryption", True if settings.token_encryption_key else None, "Token encryption key (TOKEN_ENCRYPTION_KEY)",
        "Set — tokens are encrypted with it" if settings.token_encryption_key else "Not set — using a key derived from JWT_SECRET (fine for development; set your own in production)")
    add("consent", None, "OAuth consent screen",
        "Publish the app (In production), or add every Google account that will connect as a Test user — otherwise Google shows “Access blocked”.",
        f"https://console.cloud.google.com/apis/credentials/consent{proj}")

    # The API's own overview page has the Enable button. The Library page can't be used: the Google My Business API (v4)
    # isn't listed there publicly, so its Library page fails to load.
    apis = [{"api": a, "name": n, "used_for": u, "status": "unknown", "detail": "", "enable_url": f"https://console.cloud.google.com/apis/api/{a}/overview{proj}",
             "quota_url": f"https://console.cloud.google.com/apis/api/{a}/quotas{proj}"} for a, n, u in APIS]
    probe = None
    if live and settings.google_configured:
        holder = db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == user.tenant_id, GoogleConnection.status == "active").limit(1))
        if holder is None:
            holder = next((g for g in db.scalars(select(GmbAccount).where(GmbAccount.tenant_id == user.tenant_id, GmbAccount.refresh_token_enc != ""))
                           if g.has_own_token), None)
        if holder is None:
            probe = {"status": "skipped", "detail": "Connect a Google account first, then run the live check."}
        else:
            email = getattr(holder, "email", None) or holder.google_email
            probe = {"status": "ok", "email": email, "detail": ""}
            by = {a["api"]: a for a in apis}

            def mark(key: str, fn):
                try:
                    fn()
                    by[key]["status"], by[key]["detail"] = "ok", "Working"
                    return True
                except api.GoogleApiError as e:
                    by[key]["status"], by[key]["detail"] = _classify(e)
                    if key == "mybusiness.googleapis.com" and by[key]["status"] == "disabled":
                        by[key]["detail"] += (" Open Enable while signed in to Google Cloud with the account that owns project "
                                              f"{num}. If the page says the API can't be found, Google hasn't approved Business "
                                              "Profile API access for this project yet — use “Request Business Profile API access”.")
                    by[key]["detail"] += f" ({e})"
                    return False

            try:
                g = service.client_for(holder)
                accounts: list[dict] = []
                mark(APIS[0][0], lambda: accounts.extend(g.accounts()))
                locs: list[dict] = []
                if accounts:
                    mark(APIS[1][0], lambda: locs.extend(g.locations(accounts[0]["name"])))
                if locs:
                    acct, loc = accounts[0]["name"], locs[0]["name"]
                    mark(APIS[2][0], lambda: g._get(f"{api.V4_BASE}/{acct}/{loc}/reviews", pageSize=1))
                    day = datetime.now(timezone.utc).date() - timedelta(days=3)
                    mark(APIS[3][0], lambda: g.daily_metrics(loc, day, day))
                for a in apis:
                    if a["status"] == "unknown":
                        a["detail"] = "Not tested — needs a working step before it (an account with at least one location)."
            except api.GoogleApiError as e:
                probe = {"status": "fail", "email": email, "detail": _classify(e)[1] + f" ({e})"}
            db.commit()
    return {"project_number": num, "checks": checks, "apis": apis, "live": probe,
            "access_request_url": "https://support.google.com/business/contact/api_default"}

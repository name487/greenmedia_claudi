"""Meta (Facebook Pages + Instagram): connect a Facebook login, then link each client to its Page (and the Page's Instagram)."""

import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..google.crypto import decrypt, encrypt
from ..meta import api
from ..models import Client, MetaConnectAttempt, MetaConnection, SocialAccount, User
from ..security import audit, can, current_user, get_client, load_role, require
from ..serializers import iso

router = APIRouter(prefix="/api/meta", tags=["meta"])
client_router = APIRouter(prefix="/api/clients/{client_id}/meta", tags=["meta"])

NEEDED = {"pages_show_list", "pages_manage_posts"}


def _require_configured():
    if not settings.meta_configured:
        raise HTTPException(503, "Meta is not configured on the server: set META_APP_ID, META_APP_SECRET and META_REDIRECT_URI in backend/.env.")


def _conn_out(c: MetaConnection, linked: int) -> dict:
    return {"id": c.id, "name": c.name, "fb_user_id": c.fb_user_id, "status": c.status, "last_error": c.last_error, "linked_accounts": linked,
            "token_expires_at": iso(c.token_expires_at), "scopes": c.scopes.split(",") if c.scopes else [], "created_at": iso(c.created_at)}


def account_out(a: SocialAccount) -> dict:
    return {"id": a.id, "platform": a.platform, "handle": a.handle, "name": a.name, "status": a.status, "is_live": a.is_live,
            "external_id": a.external_id, "last_error": a.last_error, "connected_at": iso(a.connected_at), "meta_connection_id": a.meta_connection_id}


@router.get("/status")
def status(user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    conns = list(db.scalars(select(MetaConnection).where(MetaConnection.tenant_id == user.tenant_id).order_by(MetaConnection.id)))
    live = [a for a in db.scalars(select(SocialAccount).where(SocialAccount.tenant_id == user.tenant_id, SocialAccount.meta_connection_id.is_not(None)))]
    return {"configured": settings.meta_configured, "redirect_uri": settings.meta_redirect_uri, "graph_version": settings.meta_graph_version,
            "app_id": settings.meta_app_id, "scopes": api.SCOPES,
            "connections": [_conn_out(c, sum(a.meta_connection_id == c.id for a in live)) for c in conns]}


@router.post("/connect")
def connect(user: User = Depends(require("client.edit"))):
    """Facebook's consent URL. The user logs in with the Facebook account that manages the clients' Pages."""
    _require_configured()
    state = jwt.encode({"tid": user.tenant_id, "uid": user.id, "purpose": "meta_oauth", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
                       settings.jwt_secret, algorithm="HS256")
    return {"auth_url": api.auth_url(state)}


def _back(result: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.web_app_url}/social/?meta={quote(result)}#meta", status_code=303)


@router.get("/callback", include_in_schema=False)
def callback(state: str = "", code: str = "", error: str = "", error_reason: str = "", db: Session = Depends(get_db)):
    try:
        st = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
        assert st.get("purpose") in ("meta_oauth", "meta_app")
    except (jwt.PyJWTError, AssertionError):
        return _back("error:invalid_or_expired_state")
    if st["purpose"] == "meta_app":
        return _app_callback(db, st, code, error, error_reason)
    if error:
        return _back(f"error:{error_reason or error}")
    user = db.get(User, st["uid"])
    if not user or user.tenant_id != st["tid"] or user.status != "active" or not can(load_role(db, user), "client.edit"):
        return _back("error:not_allowed")
    try:
        short = api.exchange_code(code)["access_token"]
        long = api.long_lived(short)
        token = long["access_token"]
        who = api.me(token)
        scopes = api.granted_scopes(token)
    except api.MetaApiError as e:
        return _back(f"error:{e}")
    missing = NEEDED - set(scopes)
    if missing:
        return _back(f"error:these permissions were not granted: {', '.join(sorted(missing))} — connect again and allow them")
    conn = db.scalar(select(MetaConnection).where(MetaConnection.tenant_id == user.tenant_id, MetaConnection.fb_user_id == who["id"]))
    if conn is None:
        conn = MetaConnection(tenant_id=user.tenant_id, fb_user_id=who["id"], user_token_enc="", connected_by=user.id)
        db.add(conn)
    conn.name, conn.user_token_enc, conn.scopes, conn.status, conn.last_error = who.get("name", ""), encrypt(token), ",".join(scopes), "active", ""
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(long.get("expires_in") or 60 * 24 * 3600))
    db.flush()
    # Reconnecting refreshes the Page tokens of accounts already linked through this login
    refreshed = _refresh_linked(db, conn, token)
    audit(db, user, f"connected Meta account {conn.name}", entity_type="meta_connection", entity_id=conn.id,
          details={"scopes": scopes, "refreshed_accounts": refreshed})
    db.commit()
    return _back(f"connected:{conn.name}")


def _refresh_linked(db: Session, conn: MetaConnection, user_token: str) -> int:
    linked = list(db.scalars(select(SocialAccount).where(SocialAccount.meta_connection_id == conn.id)))
    if not linked:
        return 0
    try:
        by_page = {p["id"]: p for p in api.pages(user_token)}
    except api.MetaApiError:
        return 0
    n = 0
    for a in linked:
        page = by_page.get(a.external_id) or next((p for p in by_page.values() if (p.get("instagram_business_account") or {}).get("id") == a.external_id), None)
        if page and page.get("access_token"):
            a.access_token_enc, a.status, a.last_error = encrypt(page["access_token"]), "connected", ""
            n += 1
    return n


def _conn(db: Session, user: User, conn_id: int) -> MetaConnection:
    c = db.get(MetaConnection, conn_id)
    if not c or c.tenant_id != user.tenant_id:
        raise HTTPException(404, "Meta connection not found")
    return c


def _pages(db: Session, conn: MetaConnection) -> list[dict]:
    try:
        return api.pages(decrypt(conn.user_token_enc))
    except api.MetaApiError as e:
        conn.last_error = str(e)
        if e.auth_failed:
            conn.status = "expired"
        db.commit()
        raise HTTPException(502, str(e)) from e
    except ValueError as e:  # token can't be decrypted (key changed)
        raise HTTPException(502, str(e)) from e


@router.get("/pages")
def pages(user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Every Facebook Page the connected logins manage, its Instagram account, and the client it's linked to. No tokens."""
    _require_configured()
    linked = {(a.platform, a.external_id): a.client_id for a in db.scalars(select(SocialAccount).where(SocialAccount.tenant_id == user.tenant_id))
              if a.is_live}
    names = dict(db.execute(select(Client.id, Client.company_name).where(Client.tenant_id == user.tenant_id)).all())
    out, errors = [], []
    for conn in db.scalars(select(MetaConnection).where(MetaConnection.tenant_id == user.tenant_id, MetaConnection.status == "active")):
        try:
            for p in _pages(db, conn):
                ig = p.get("instagram_business_account") or {}
                cid = linked.get(("facebook", p["id"]))
                out.append({"connection_id": conn.id, "connected_as": conn.name, "page_id": p["id"], "name": p.get("name", ""),
                            "picture": ((p.get("picture") or {}).get("data") or {}).get("url", ""), "can_post": "CREATE_CONTENT" in (p.get("tasks") or ["CREATE_CONTENT"]),
                            "instagram": {"id": ig["id"], "username": ig.get("username", "")} if ig else None,
                            "linked_client_id": cid, "linked_client_name": names.get(cid)})
        except HTTPException as e:
            errors.append({"connected_as": conn.name, "error": e.detail})
    return {"pages": out, "errors": errors}


@router.delete("/connections/{conn_id}")
def disconnect(conn_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    conn = _conn(db, user, conn_id)
    try:
        api.revoke(decrypt(conn.user_token_enc))
    except ValueError:
        pass
    n = 0
    for a in db.scalars(select(SocialAccount).where(SocialAccount.meta_connection_id == conn.id)):
        _unlink(a)
        n += 1
    audit(db, user, f"disconnected Meta account {conn.name}", entity_type="meta_connection", entity_id=conn.id, details={"unlinked_accounts": n})
    db.delete(conn)
    db.commit()
    return {"ok": True, "unlinked_accounts": n}


# ---------- per client ----------

def _unlink(a: SocialAccount) -> None:
    a.access_token_enc, a.external_id, a.meta_connection_id, a.status = "", "", None, "expired"
    a.last_error = "Disconnected — link a Page again to publish"


class LinkIn(BaseModel):
    connection_id: int
    page_id: str
    instagram: bool = True  # also link the Page's Instagram professional account (when it has one)


@client_router.get("")
def client_accounts(client_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    return {"configured": settings.meta_configured, "accounts": [account_out(a) for a in c.social_accounts if a.platform in ("facebook", "instagram")]}


def _link_page(db: Session, user: User, c: Client, conn: MetaConnection, page: dict, instagram: bool = True) -> list[str]:
    """Link the client to a Page (and its Instagram). Raises HTTPException when the Page can't be used."""
    if not page.get("access_token"):
        raise HTTPException(403, "No Page access token — the login needs a role on the Page that can create content")
    taken = db.scalar(select(SocialAccount).where(SocialAccount.tenant_id == c.tenant_id, SocialAccount.platform == "facebook",
                                                  SocialAccount.external_id == page["id"], SocialAccount.client_id != c.id))
    if taken:
        raise HTTPException(409, "That Page is already linked to another client")
    now = datetime.now(timezone.utc)
    token = encrypt(page["access_token"])
    ig = page.get("instagram_business_account") or {}
    targets = [("facebook", page["id"], page.get("name", ""), page.get("name", ""))]
    if instagram and ig:
        targets.append(("instagram", ig["id"], ig.get("username", ""), f"@{ig.get('username', '')}"))
    linked = []
    for platform, ext_id, name, handle in targets:
        a = next((x for x in c.social_accounts if x.platform == platform), None)
        if a is None:
            a = SocialAccount(tenant_id=c.tenant_id, client_id=c.id, platform=platform)
            c.social_accounts.append(a)
        a.external_id, a.name, a.handle, a.access_token_enc, a.meta_connection_id = ext_id, name, handle, token, conn.id
        a.status, a.last_error, a.connected_at = "connected", "", now
        linked.append(platform)
    db.flush()
    audit(db, user, f"linked Facebook Page “{page.get('name')}”" + (f" and Instagram @{ig.get('username')}" if "instagram" in linked else ""),
          client_id=c.id, entity_type="social_account", entity_id=page["id"], details={"platforms": linked, "page_id": page["id"], "instagram_id": ig.get("id")})
    return linked


@client_router.post("/link")
def link(client_id: int, body: LinkIn, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    """Link the client's Facebook Page (and its Instagram) for publishing. Verified against Meta; stores the Page token encrypted."""
    _require_configured()
    c = get_client(db, user, client_id)
    conn = _conn(db, user, body.connection_id)
    page = next((p for p in _pages(db, conn) if p["id"] == body.page_id), None)
    if not page:
        raise HTTPException(404, "That Facebook login doesn't manage this Page")
    linked = _link_page(db, user, c, conn, page, body.instagram)
    db.commit()
    return {"linked": linked, "instagram_available": bool(page.get("instagram_business_account")),
            "accounts": [account_out(a) for a in c.social_accounts if a.platform in ("facebook", "instagram")]}


@client_router.delete("")
def unlink(client_id: int, user: User = Depends(require("client.edit")), db: Session = Depends(get_db)):
    c = get_client(db, user, client_id)
    done = []
    for a in c.social_accounts:
        if a.platform in ("facebook", "instagram") and a.is_live:
            _unlink(a)
            done.append(a.platform)
    audit(db, user, f"unlinked Meta accounts: {', '.join(done) or 'none'}", client_id=c.id, entity_type="social_account")
    db.commit()
    return {"unlinked": done}


# ---------- connect from the mobile app (business owners and staff) ----------

PLATFORM_LABEL = {"facebook": "Facebook", "instagram": "Instagram"}
FAIL_MESSAGES = {
    "cancelled": "The {p} screen closed before the connection was saved — either it was dismissed, or {p} ended it on its own.",
    "permissions": "Some permissions were switched off on {p}'s screen. Connect again and keep every toggle on.",
    "no_pages": "This Facebook account doesn't manage any Facebook Page. Log in with the account that is an admin of your business Page.",
    "no_instagram": "None of your Facebook Pages has an Instagram professional (Business or Creator) account linked to it.",
    "page_taken": "Your Page is already connected to another business in our system — please contact your account manager.",
    "not_configured": "Facebook connection isn't set up on the server yet — please contact your account manager.",
}


def _may_connect(user: User, c: Client) -> bool:
    return can(user, "client.edit") or user.client_id == c.id


def _attempt_out(a: MetaConnectAttempt, c: Client) -> dict:
    return {"id": a.token, "platform": a.platform, "status": a.status, "reason": a.reason, "message": a.message,
            "candidates": a.candidates or [], "accounts": [account_out(x) for x in c.social_accounts if x.platform in ("facebook", "instagram")]}


def _fail(a: MetaConnectAttempt, reason: str, message: str = "") -> None:
    a.status, a.reason, a.finished_at = "failed", reason, datetime.now(timezone.utc)
    a.message = message or FAIL_MESSAGES.get(reason, FAIL_MESSAGES["cancelled"]).format(p=PLATFORM_LABEL[a.platform])


class AppConnectIn(BaseModel):
    platform: str = "facebook"


@client_router.post("/connect", status_code=201)
def app_connect(client_id: int, body: AppConnectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start connecting Facebook or Instagram from the app. Open auth_url, then poll GET …/connect/{id}."""
    c = get_client(db, load_role(db, user), client_id)
    if body.platform not in PLATFORM_LABEL:
        raise HTTPException(422, "platform must be facebook or instagram")
    if not _may_connect(user, c):
        raise HTTPException(403, "Your role cannot connect social accounts")
    if not settings.meta_configured:
        raise HTTPException(503, FAIL_MESSAGES["not_configured"])
    a = MetaConnectAttempt(token=secrets.token_urlsafe(16), tenant_id=c.tenant_id, client_id=c.id, user_id=user.id, platform=body.platform)
    db.add(a)
    db.commit()
    state = jwt.encode({"purpose": "meta_app", "aid": a.token, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}, settings.jwt_secret,
                       algorithm="HS256")
    return {"id": a.token, "auth_url": api.auth_url(state)}


def _attempt(db: Session, user: User, c: Client, token: str) -> MetaConnectAttempt:
    a = db.scalar(select(MetaConnectAttempt).where(MetaConnectAttempt.token == token, MetaConnectAttempt.client_id == c.id))
    if not a:
        raise HTTPException(404, "Connection attempt not found")
    return a


@client_router.get("/connect/{token}")
def app_connect_status(client_id: int, token: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_client(db, load_role(db, user), client_id)
    return _attempt_out(_attempt(db, user, c, token), c)


@client_router.post("/connect/{token}/cancel")
def app_connect_cancel(client_id: int, token: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The app came back without the login finishing (back button, closed tab)."""
    c = get_client(db, load_role(db, user), client_id)
    a = _attempt(db, user, c, token)
    if a.status == "pending":
        _fail(a, "cancelled")
        db.commit()
    return _attempt_out(a, c)


class ChooseIn(BaseModel):
    page_id: str


@client_router.post("/connect/{token}/choose")
def app_connect_choose(client_id: int, token: str, body: ChooseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_client(db, load_role(db, user), client_id)
    a = _attempt(db, user, c, token)
    if a.status != "choose_page" or not any(x["page_id"] == body.page_id for x in a.candidates or []):
        raise HTTPException(409, "Pick one of the Pages listed")
    conn = db.get(MetaConnection, a.connection_id)
    page = next((p for p in _pages(db, conn) if p["id"] == body.page_id), None) if conn else None
    if not page:
        raise HTTPException(404, "That Facebook login no longer manages this Page — connect again")
    _link_page(db, load_role(db, user), c, conn, page, instagram=True)
    a.status, a.reason, a.message, a.finished_at = "connected", "", "", datetime.now(timezone.utc)
    db.commit()
    return _attempt_out(a, c)


def _app_page(ok: bool, title: str, text: str) -> HTMLResponse:
    colour = "#0f7a45" if ok else "#c53030"
    return HTMLResponse(f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>body{{font-family:system-ui,-apple-system,Roboto,sans-serif;margin:0;padding:32px 20px;text-align:center;color:#14231b}}
h1{{font-size:20px;color:{colour}}} p{{color:#5b6b62}}</style></head><body><h1>{escape(title)}</h1><p>{escape(text)}</p>
<p><b>Go back to the app</b> — it updates by itself.</p></body></html>""")


def _app_callback(db: Session, st: dict, code: str, error: str, error_reason: str) -> HTMLResponse:
    a = db.scalar(select(MetaConnectAttempt).where(MetaConnectAttempt.token == st.get("aid")))
    if not a:
        return _app_page(False, "Link expired", "Start again from the app.")
    label = PLATFORM_LABEL[a.platform]
    c, user = db.get(Client, a.client_id), db.get(User, a.user_id)
    if error:
        _fail(a, "cancelled" if (error_reason or error) in ("user_denied", "access_denied") else "error",
              "" if (error_reason or error) in ("user_denied", "access_denied") else f"{label} said: {error_reason or error}")
        db.commit()
        return _app_page(False, f"{label} didn't finish connecting", a.message)
    if not c or not user or user.status != "active" or not _may_connect(load_role(db, user), c):
        _fail(a, "error", "You can no longer connect accounts for this business.")
        db.commit()
        return _app_page(False, "Not allowed", a.message)
    try:
        token = api.long_lived(api.exchange_code(code)["access_token"])
        who, scopes = api.me(token["access_token"]), api.granted_scopes(token["access_token"])
        missing = NEEDED | ({"instagram_basic", "instagram_content_publish"} if a.platform == "instagram" else set())
        if missing - set(scopes):
            _fail(a, "permissions")
            db.commit()
            return _app_page(False, f"{label} didn't finish connecting", a.message)
        conn = db.scalar(select(MetaConnection).where(MetaConnection.tenant_id == c.tenant_id, MetaConnection.fb_user_id == who["id"]))
        if conn is None:
            conn = MetaConnection(tenant_id=c.tenant_id, fb_user_id=who["id"], user_token_enc="", connected_by=user.id)
            db.add(conn)
        conn.name, conn.user_token_enc, conn.scopes, conn.status, conn.last_error = who.get("name", ""), encrypt(token["access_token"]), ",".join(scopes), "active", ""
        conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in") or 60 * 24 * 3600))
        db.flush()
        a.connection_id = conn.id
        pages = api.pages(token["access_token"])
    except api.MetaApiError as e:
        _fail(a, "error", f"{label} returned an error: {e}")
        db.commit()
        return _app_page(False, f"{label} didn't finish connecting", a.message)
    taken = {x.external_id for x in db.scalars(select(SocialAccount).where(SocialAccount.tenant_id == c.tenant_id, SocialAccount.platform == "facebook",
                                                                             SocialAccount.client_id != c.id, SocialAccount.external_id != ""))}
    usable = [p for p in pages if p.get("access_token") and p["id"] not in taken]
    if a.platform == "instagram":
        usable = [p for p in usable if p.get("instagram_business_account")]
    if not usable:
        _fail(a, "page_taken" if pages and all(p["id"] in taken for p in pages) else "no_instagram" if a.platform == "instagram" and pages else "no_pages")
        db.commit()
        return _app_page(False, f"{label} didn't finish connecting", a.message)
    if len(usable) > 1:
        a.status = "choose_page"
        a.candidates = [{"page_id": p["id"], "name": p.get("name", ""), "picture": ((p.get("picture") or {}).get("data") or {}).get("url", ""),
                         "instagram": (p.get("instagram_business_account") or {}).get("username")} for p in usable]
        db.commit()
        return _app_page(True, "Almost done", "Go back to the app and choose your business Page.")
    _link_page(db, load_role(db, user), c, conn, usable[0], instagram=True)
    a.status, a.finished_at = "connected", datetime.now(timezone.utc)
    db.commit()
    return _app_page(True, f"{label} connected", f"{usable[0].get('name', 'Your Page')} is now connected.")

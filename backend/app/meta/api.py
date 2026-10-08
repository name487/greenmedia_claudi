"""Meta Graph API: Facebook Login (OAuth), Pages, and publishing to Facebook Pages and Instagram professional accounts.

Permissions requested (Facebook Login for Business):
  pages_show_list, pages_read_engagement, pages_manage_posts        → list Pages, post to them
  instagram_basic, instagram_content_publish                         → post to the Instagram account linked to a Page
  business_management                                                → Pages owned through a Business portfolio

Flow: user token (short-lived) → long-lived user token (~60 days) → /me/accounts gives each Page's access token.
Page tokens obtained from a long-lived user token don't expire (unless the user changes password / removes the app),
so publishing keeps working without the agency having to log in again.
"""

from urllib.parse import urlencode

import httpx

from ..config import settings

# Swappable in tests (httpx.MockTransport).
http = httpx.Client(timeout=30)

SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic", "instagram_content_publish", "business_management"]
TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 613, 80001, 80002, 80004}  # unknown/service errors and rate limits
AUTH_CODES = {190, 102}  # token invalid or expired: the user must reconnect


def graph() -> str:
    return f"https://graph.facebook.com/{settings.meta_graph_version}"


class MetaApiError(Exception):
    def __init__(self, status: int, message: str, code: int | None = None, subcode: int | None = None, transient: bool | None = None, trace: str = ""):
        super().__init__(message)
        self.status, self.code, self.subcode, self.trace = status, code, subcode, trace
        self._transient = transient

    @property
    def auth_failed(self) -> bool:
        return self.code in AUTH_CODES or self.status == 401

    @property
    def transient(self) -> bool:
        if self.auth_failed:
            return False
        if self._transient is not None:
            return self._transient
        return self.code in TRANSIENT_CODES or self.status >= 500 or self.status == 429


def _check(r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code < 400 and "error" not in body:
        return body
    err = body.get("error") or {}
    code, sub = err.get("code"), err.get("error_subcode")
    msg = err.get("error_user_msg") or err.get("message") or r.text[:300]
    hint = ""
    if code in AUTH_CODES:
        hint = " — the Facebook login expired or was revoked; reconnect Meta."
    elif code in (10, 200) or (code and 200 <= code < 300):
        hint = " — a permission is missing: reconnect Meta and allow all requested permissions (and check the app's Advanced Access)."
    elif code in (4, 17, 32, 613):
        hint = " — Meta rate limit; it will be retried."
    raise MetaApiError(r.status_code, f"Meta {r.status_code} (code {code}{f'/{sub}' if sub else ''}): {msg}{hint}", code, sub,
                       err.get("is_transient"), err.get("fbtrace_id", ""))


def _get(path: str, **params) -> dict:
    return _check(http.get(f"{graph()}/{path.lstrip('/')}", params=params))


def _post(path: str, **data) -> dict:
    return _check(http.post(f"{graph()}/{path.lstrip('/')}", data={k: v for k, v in data.items() if v not in (None, "")}))


# ---------- OAuth ----------

def auth_url(state: str) -> str:
    return f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?" + urlencode({
        "client_id": settings.meta_app_id, "redirect_uri": settings.meta_redirect_uri, "state": state,
        "response_type": "code", "scope": ",".join(SCOPES),
    })


def exchange_code(code: str) -> dict:
    return _get("oauth/access_token", client_id=settings.meta_app_id, client_secret=settings.meta_app_secret,
                redirect_uri=settings.meta_redirect_uri, code=code)


def long_lived(user_token: str) -> dict:
    """{"access_token", "expires_in" (~60 days)}"""
    return _get("oauth/access_token", grant_type="fb_exchange_token", client_id=settings.meta_app_id,
                client_secret=settings.meta_app_secret, fb_exchange_token=user_token)


def me(user_token: str) -> dict:
    return _get("me", fields="id,name", access_token=user_token)


def granted_scopes(user_token: str) -> list[str]:
    return [p["permission"] for p in _get("me/permissions", access_token=user_token).get("data", []) if p.get("status") == "granted"]


def pages(user_token: str) -> list[dict]:
    """Pages the user can manage, each with its Page access token and linked Instagram professional account."""
    out, after = [], None
    for _ in range(10):
        body = _get("me/accounts", access_token=user_token, limit=100, after=after,
                    fields="id,name,access_token,tasks,picture{url},instagram_business_account{id,username,profile_picture_url}")
        out += body.get("data", [])
        after = ((body.get("paging") or {}).get("cursors") or {}).get("after") if (body.get("paging") or {}).get("next") else None
        if not after:
            break
    return out


def revoke(user_token: str) -> None:
    """Best effort: remove the app's permissions for this user."""
    try:
        http.delete(f"{graph()}/me/permissions", params={"access_token": user_token})
    except Exception:  # noqa: BLE001
        pass


# ---------- publishing ----------

def publish_facebook(page_id: str, page_token: str, message: str, image_url: str = "", link: str = "") -> str:
    """Text/link post → POST /{page}/feed; with an image → POST /{page}/photos (caption = message). Returns the post id."""
    if image_url:
        body = _post(f"{page_id}/photos", url=image_url, caption=message, access_token=page_token)
        return body.get("post_id") or body["id"]
    return _post(f"{page_id}/feed", message=message, link=link or None, access_token=page_token)["id"]


def publish_instagram(ig_user_id: str, page_token: str, caption: str, image_url: str) -> str:
    """Two steps: create a media container from a public image URL, then publish it. Returns the media id."""
    container = _post(f"{ig_user_id}/media", image_url=image_url, caption=caption, access_token=page_token)["id"]
    try:
        return _post(f"{ig_user_id}/media_publish", creation_id=container, access_token=page_token)["id"]
    except MetaApiError as e:
        if e.code == 9007:  # media not ready yet
            raise MetaApiError(e.status, str(e), e.code, e.subcode, transient=True) from e
        raise

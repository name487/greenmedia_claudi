"""Thin client for the FastAPI backend. Views never talk to a database; they talk to this."""

from functools import wraps

import httpx
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

SESSION_TOKEN = "api_token"
SESSION_ME = "me"


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class Api:
    def __init__(self, token: str | None = None):
        self.token = token

    def _request(self, method: str, path: str, **kw):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            r = httpx.request(method, f"{settings.API_URL}{path}", headers=headers, timeout=settings.API_TIMEOUT, **kw)
        except httpx.HTTPError as e:
            raise ApiError(503, f"API unavailable ({e.__class__.__name__}). Is the FastAPI server running at {settings.API_URL}?")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            if isinstance(detail, list):  # FastAPI validation errors
                detail = "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detail)
            raise ApiError(r.status_code, str(detail))
        return r.json() if r.content else None

    def get(self, path: str, **params):
        return self._request("GET", path, params={k: v for k, v in params.items() if v not in (None, "", "all")})

    def post(self, path: str, json: dict | None = None):
        return self._request("POST", path, json=json or {})

    def patch(self, path: str, json: dict):
        return self._request("PATCH", path, json=json)

    def delete(self, path: str):
        return self._request("DELETE", path)


def api_for(request) -> Api:
    return Api(request.session.get(SESSION_TOKEN))


def login_required(section: str | None = None):
    """Require a session token (and optionally a role section); expose request.api and request.me.
    Turns backend 401s into a fresh login and 4xx errors into flash messages."""

    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            me = request.session.get(SESSION_ME)
            if not request.session.get(SESSION_TOKEN) or not me:
                return redirect(f"/login/?next={request.path}")
            if section and section not in me["sections"]:
                messages.error(request, "Your role does not have access to that page.")
                return redirect("dashboard")
            request.api, request.me = api_for(request), me
            try:
                return view(request, *args, **kwargs)
            except ApiError as e:
                if e.status == 401:
                    request.session.flush()
                    messages.error(request, "Your session expired. Please sign in again.")
                    return redirect(f"/login/?next={request.path}")
                messages.error(request, e.detail)
                if request.method == "POST":
                    return redirect(request.get_full_path())
                return redirect("dashboard") if request.resolver_match.url_name != "dashboard" else _unavailable(request, e)

        return wrapped

    return deco


def _unavailable(request, e: ApiError):
    from django.shortcuts import render

    return render(request, "portal/error.html", {"error": e.detail}, status=502)


def can(request, action: str) -> bool:
    return action in request.session.get(SESSION_ME, {}).get("permissions", [])

"""OAuth + HTTP client for the Google Business Profile APIs.

APIs used (enable all of them in Google Cloud Console):
- My Business Account Management API      accounts
- My Business Business Information API    locations
- Google My Business API (v4)             reviews, review replies, local posts
- Business Profile Performance API        daily insights
"""

from datetime import date, datetime
from urllib.parse import urlencode

import httpx

from ..config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
V4_BASE = "https://mybusiness.googleapis.com/v4"
PERF_BASE = "https://businessprofileperformance.googleapis.com/v1"

SCOPES = ["openid", "email", "https://www.googleapis.com/auth/business.manage"]

# Swappable in tests (httpx.MockTransport).
http = httpx.Client(timeout=30)


class GoogleApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status

    @property
    def approval_pending(self) -> bool:
        """Quota 0: Google hasn't approved Business Profile API access for this Cloud project yet."""
        return is_approval_pending(self.status, str(self))

    @property
    def auth_failed(self) -> bool:
        """Token revoked/expired beyond refresh: the user must reconnect Google."""
        return self.status == 401 or "invalid_grant" in str(self)


def is_approval_pending(status: int | None, message: str) -> bool:
    low = (message or "").lower()
    return status == 429 or "quota" in low or "resource_exhausted" in low


def _raise(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        body = r.json()
        err = body.get("error")
        msg = err.get("message") if isinstance(err, dict) else f"{err}: {body.get('error_description', '')}"
    except ValueError:
        msg = r.text[:300]
    hint = ""
    if r.status_code == 429 or "quota" in (msg or "").lower():
        hint = " — Business Profile API quota is 0 until Google approves your API access request."
    elif r.status_code == 403:
        hint = " — check that the API is enabled in Google Cloud and the Google account manages this profile."
    raise GoogleApiError(r.status_code, f"Google API {r.status_code}: {msg}{hint}")


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------- OAuth ----------

def auth_url(state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # we need a refresh token for background sync
        "prompt": "consent",       # always return a refresh token, even on reconnect
        "include_granted_scopes": "true",
        "state": state,
    })


def exchange_code(code: str) -> dict:
    r = http.post(TOKEN_URL, data={
        "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code",
    })
    _raise(r)
    return r.json()


def refresh(refresh_token: str) -> dict:
    """Trade a refresh token for a new access token: {"access_token", "expires_in", maybe "refresh_token"}.
    Callers persist the result (see tokens.py), so every worker and restart reuses it until it expires."""
    r = http.post(TOKEN_URL, data={
        "refresh_token": refresh_token, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "grant_type": "refresh_token",
    })
    _raise(r)
    return r.json()


def revoke(token: str) -> None:
    """Best effort: tell Google to drop the grant. Never raises."""
    try:
        http.post(REVOKE_URL, data={"token": token})
    except Exception:  # noqa: BLE001
        pass


def userinfo_email(token: str) -> str:
    r = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {token}"})
    _raise(r)
    return r.json().get("email", "")


# ---------- Business Profile ----------

class Gbp:
    def __init__(self, token: str, renew=None):
        """renew: optional callable returning a fresh access token; used once if Google answers 401
        (token revoked or expired early), so a stale stored token heals itself."""
        self.h = {"Authorization": f"Bearer {token}"}
        self._renew = renew

    def _send(self, method: str, url: str, **kw) -> httpx.Response:
        r = http.request(method, url, headers=self.h, **kw)
        if r.status_code == 401 and self._renew:
            self.h = {"Authorization": f"Bearer {self._renew()}"}
            self._renew = None
            r = http.request(method, url, headers=self.h, **kw)
        _raise(r)
        return r

    def _get(self, url: str, **params) -> dict:
        return self._send("GET", url, params={k: v for k, v in params.items() if v is not None}).json()

    def _paged(self, url: str, key: str, **params) -> list[dict]:
        out, token = [], None
        while True:
            body = self._get(url, pageToken=token, **params)
            out += body.get(key, [])
            token = body.get("nextPageToken")
            if not token:
                return out

    def accounts(self) -> list[dict]:
        return self._paged(ACCOUNTS_URL, "accounts", pageSize=20)

    def locations(self, account: str) -> list[dict]:
        return self._paged(f"{INFO_BASE}/{account}/locations", "locations", pageSize=100,
                           readMask="name,title,storefrontAddress,websiteUri,phoneNumbers,metadata")

    def reviews(self, account: str, location: str, max_pages: int = 10, since: datetime | None = None) -> dict:
        """Returns {"reviews": [...], "averageRating": x, "totalReviewCount": n}, most recently updated first.
        With `since`, paging stops once a page reaches reviews not updated after it (incremental sync)."""
        url = f"{V4_BASE}/{account}/{location}/reviews"
        out: dict = {"reviews": []}
        token = None
        for _ in range(max_pages):
            body = self._get(url, pageSize=50, pageToken=token, orderBy="updateTime desc")
            page = body.get("reviews", [])
            out["reviews"] += page
            out["averageRating"] = body.get("averageRating", out.get("averageRating"))
            out["totalReviewCount"] = body.get("totalReviewCount", out.get("totalReviewCount"))
            token = body.get("nextPageToken")
            if not token or (since and page and (parse_time(page[-1].get("updateTime")) or since) <= since):
                break
        return out

    def reply(self, account: str, location: str, review_id: str, comment: str) -> dict:
        return self._send("PUT", f"{V4_BASE}/{account}/{location}/reviews/{review_id}/reply", json={"comment": comment}).json()

    def create_post(self, account: str, location: str, summary: str, url: str | None = None) -> dict:
        body: dict = {"languageCode": "en", "summary": summary[:1500], "topicType": "STANDARD"}
        if url:
            body["callToAction"] = {"actionType": "LEARN_MORE", "url": url}
        return self._send("POST", f"{V4_BASE}/{account}/{location}/localPosts", json=body).json()

    def daily_metrics(self, location: str, start: date, end: date) -> dict[str, dict[date, int]]:
        metrics = ["BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
                   "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS"]
        params = [("dailyMetrics", m) for m in metrics] + [
            ("dailyRange.start_date.year", start.year), ("dailyRange.start_date.month", start.month), ("dailyRange.start_date.day", start.day),
            ("dailyRange.end_date.year", end.year), ("dailyRange.end_date.month", end.month), ("dailyRange.end_date.day", end.day),
        ]
        r = self._send("GET", f"{PERF_BASE}/{location}:fetchMultiDailyMetricsTimeSeries", params=params)
        out: dict[str, dict[date, int]] = {}
        for group in r.json().get("multiDailyMetricTimeSeries", []):
            for series in group.get("dailyMetricTimeSeries", []):
                vals = out.setdefault(series["dailyMetric"], {})
                for dv in series.get("timeSeries", {}).get("datedValues", []):
                    d = dv["date"]
                    vals[date(d["year"], d["month"], d["day"])] = int(dv.get("value", 0) or 0)
        return out

    def search_keywords(self, location: str, start: date, end: date, max_pages: int = 5) -> list[tuple[str, int, bool]]:
        """Search terms that showed the profile between the months of start and end, as (keyword, impressions,
        below_threshold). Google hides exact counts for rare terms and gives only an upper bound ("threshold")."""
        params = {"monthlyRange.start_month.year": start.year, "monthlyRange.start_month.month": start.month,
                  "monthlyRange.end_month.year": end.year, "monthlyRange.end_month.month": end.month, "pageSize": 100}
        out, token = [], None
        for _ in range(max_pages):
            body = self._get(f"{PERF_BASE}/{location}/searchkeywords/impressions/monthly", pageToken=token, **params)
            for row in body.get("searchKeywordsCounts", []):
                v = row.get("insightsValue") or {}
                if "value" in v:
                    out.append((row.get("searchKeyword", ""), int(v["value"]), False))
                elif "threshold" in v:
                    out.append((row.get("searchKeyword", ""), int(v["threshold"]), True))
            token = body.get("nextPageToken")
            if not token:
                break
        return out

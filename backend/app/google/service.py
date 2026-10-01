"""Business logic on top of the Google API client: link locations, sync reviews + insights, publish."""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Client, GmbAccount, GoogleConnection, MetricDaily, Review
from ..sentiment import detect_language, detect_sentiment
from . import api, tokens

log = logging.getLogger("greenmedia.google")

STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def source(gmb: GmbAccount) -> GoogleConnection | GmbAccount:
    """Where this location's Google access comes from: the agency connection it was linked through,
    otherwise the client's own sign-in stored on the gmb_accounts row."""
    if gmb.connection_id is not None:
        return gmb.connection
    if gmb.refresh_token_enc:
        return gmb
    raise api.GoogleApiError(401, "This client has no Google sign-in — connect Google first.")


def mark_revoked(holder, err: Exception) -> None:
    tokens.clear(holder)
    if isinstance(holder, GoogleConnection):
        holder.status, holder.last_error = "revoked", str(err)
    else:
        holder.token_status, holder.status, holder.last_error = "revoked", "expired", str(err)


def client_for(holder: GoogleConnection | GmbAccount) -> api.Gbp:
    def renew() -> str:
        try:
            return tokens.access_token(holder, force_refresh=True)
        except api.GoogleApiError as e:
            if e.auth_failed:
                mark_revoked(holder, e)
            raise
    try:
        return api.Gbp(tokens.access_token(holder), renew=renew)
    except api.GoogleApiError as e:
        if e.auth_failed:
            mark_revoked(holder, e)
        raise


def _loc_out(acct: dict, loc: dict) -> dict:
    addr = loc.get("storefrontAddress") or {}
    return {
        "account": acct["name"],
        "account_name": acct.get("accountName", ""),
        "location": loc["name"],  # "locations/123"
        "title": loc.get("title", ""),
        "address": ", ".join(filter(None, [*(addr.get("addressLines") or []), addr.get("locality", "")])),
        "website": loc.get("websiteUri", ""),
        "phone": (loc.get("phoneNumbers") or {}).get("primaryPhone", ""),
        "maps_uri": (loc.get("metadata") or {}).get("mapsUri", ""),
    }


def list_locations(holder: GoogleConnection | GmbAccount) -> list[dict]:
    """Every location this grant can manage. connection_id is None for a client's own sign-in."""
    g = client_for(holder)
    conn_id = holder.id if isinstance(holder, GoogleConnection) else None
    return [{**_loc_out(acct, loc), "connection_id": conn_id} for acct in g.accounts() for loc in g.locations(acct["name"])]


DEMO_REVIEW_PREFIX = "demo_"


def ensure_gmb(client: Client) -> GmbAccount:
    if client.gmb is None:
        client.gmb = GmbAccount(tenant_id=client.tenant_id, location_id="", status="disconnected")
    return client.gmb


def link(db: Session, client: Client, conn: GoogleConnection | None, loc: dict) -> GmbAccount:
    """Point the client at a real location. conn=None means through the client's own sign-in."""
    gmb = ensure_gmb(client)
    if not gmb.is_live:
        # Going live: drop this client's simulated reviews and metrics so real Google data isn't mixed with demo data.
        db.execute(delete(Review).where(Review.client_id == client.id, Review.external_review_id.startswith(DEMO_REVIEW_PREFIX)))
        db.execute(delete(MetricDaily).where(MetricDaily.client_id == client.id))
    if not gmb.is_live or gmb.location_id != loc["location"]:
        gmb.rating, gmb.review_count, gmb.last_sync = 0, 0, None  # demo or other-location figures; the sync fills them in
    gmb.connection_id = conn.id if conn else None
    gmb.google_account, gmb.location_id, gmb.title = loc["account"], loc["location"], loc.get("title", "")
    gmb.address, gmb.maps_uri = loc.get("address", ""), loc.get("maps_uri", "")
    gmb.status, gmb.last_error = "connected", ""
    db.flush()
    return gmb


def unlink(gmb: GmbAccount) -> None:
    gmb.connection_id, gmb.google_account, gmb.status = None, "", "disconnected"


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def sync_reviews(db: Session, client: Client) -> dict:
    gmb = client.gmb
    g = client_for(source(gmb))
    data = g.reviews(gmb.google_account, gmb.location_id)
    existing = {r.external_review_id: r for r in db.scalars(select(Review).where(Review.client_id == client.id))}
    new = updated = 0
    for gr in data["reviews"]:
        rid = gr["reviewId"]
        text = gr.get("comment", "")
        # Google appends machine translations: "(Translated by Google) ... (Original) ..."
        if "(Original)" in text:
            text = text.split("(Original)", 1)[1].strip()
        rating = STARS.get(gr.get("starRating", ""), 0)
        reply = (gr.get("reviewReply") or {}).get("comment")
        r = existing.get(rid)
        if r is None:
            r = Review(tenant_id=client.tenant_id, client_id=client.id, external_review_id=rid, author=(gr.get("reviewer") or {}).get("displayName", "Google user"),
                       rating=rating, text=text, language=detect_language(text), sentiment=detect_sentiment(text, rating),
                       created_at=_parse_time(gr.get("createTime")) or datetime.now(timezone.utc), reply_status="new")
            db.add(r)
            new += 1
        elif r.text != text or r.rating != rating:
            r.text, r.rating, r.sentiment = text, rating, detect_sentiment(text, rating)
            updated += 1
        if reply and r.reply_status != "published":
            # Replied on Google directly (or by us earlier): mirror it so nobody drafts a second reply.
            r.reply, r.reply_status = reply, "published"
            r.published_at = _parse_time((gr.get("reviewReply") or {}).get("updateTime"))
    if data.get("averageRating") is not None:
        gmb.rating = round(float(data["averageRating"]), 1)
    if data.get("totalReviewCount") is not None:
        gmb.review_count = int(data["totalReviewCount"])
    return {"new_reviews": new, "updated_reviews": updated, "total_on_google": gmb.review_count}


def sync_metrics(db: Session, client: Client, days: int = 90) -> int:
    """Pull daily insights into analytics_daily (GMB columns only; GA4/GSC/social columns are left untouched)."""
    gmb = client.gmb
    g = client_for(source(gmb))
    end = date.today() - timedelta(days=1)  # today's data is incomplete
    start = end - timedelta(days=days - 1)
    m = g.daily_metrics(gmb.location_id, start, end)
    impressions = [m.get(k, {}) for k in ("BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
                                          "BUSINESS_IMPRESSIONS_MOBILE_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH")]
    rows = {r.date: r for r in db.scalars(select(MetricDaily).where(MetricDaily.client_id == client.id, MetricDaily.date.between(start, end)))}
    n = 0
    d = start
    while d <= end:
        row = rows.get(d) or MetricDaily(tenant_id=client.tenant_id, client_id=client.id, date=d)
        if d not in rows:
            db.add(row)
        row.gmb_views = sum(x.get(d, 0) for x in impressions)
        row.gmb_calls = m.get("CALL_CLICKS", {}).get(d, 0)
        row.web_clicks = m.get("WEBSITE_CLICKS", {}).get(d, 0)
        row.gmb_directions = m.get("BUSINESS_DIRECTION_REQUESTS", {}).get(d, 0)
        n += 1
        d += timedelta(days=1)
    return n


def sync_client(db: Session, client: Client) -> dict:
    """Full live sync. Errors are recorded on the profile so the UI can show them."""
    gmb = client.gmb
    try:
        out = sync_reviews(db, client)
        try:
            out["metric_days"] = sync_metrics(db, client)
        except api.GoogleApiError as e:  # insights are optional (Performance API may not be enabled yet)
            out["metrics_error"] = str(e)
        gmb.last_sync, gmb.status, gmb.last_error = datetime.now(timezone.utc), "connected", out.get("metrics_error", "")
        return out
    except api.GoogleApiError as e:
        gmb.last_error = str(e)
        if e.auth_failed:
            gmb.status = "expired"
        raise


def publish_reply(client: Client, review_id: str, comment: str) -> None:
    gmb = client.gmb
    client_for(source(gmb)).reply(gmb.google_account, gmb.location_id, review_id, comment)


def publish_post(client: Client, summary: str) -> str:
    gmb = client.gmb
    post = client_for(source(gmb)).create_post(gmb.google_account, gmb.location_id, summary, client.website or None)
    return post.get("name", "")

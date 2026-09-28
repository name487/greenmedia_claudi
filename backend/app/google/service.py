"""Business logic on top of the Google API client: link locations, sync reviews + insights, publish."""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Client, GmbAccount, GoogleConnection, MetricDaily, Review
from ..sentiment import detect_language, detect_sentiment
from . import api
from .crypto import decrypt

log = logging.getLogger("greenmedia.google")

STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def client_for(conn: GoogleConnection) -> api.Gbp:
    try:
        return api.Gbp(api.access_token(decrypt(conn.refresh_token_enc)))
    except api.GoogleApiError as e:
        if e.auth_failed:
            conn.status, conn.last_error = "revoked", str(e)
        raise


def list_locations(conn: GoogleConnection) -> list[dict]:
    g = client_for(conn)
    out = []
    for acct in g.accounts():
        for loc in g.locations(acct["name"]):
            addr = loc.get("storefrontAddress") or {}
            out.append({
                "connection_id": conn.id,
                "account": acct["name"],
                "account_name": acct.get("accountName", ""),
                "location": loc["name"],  # "locations/123"
                "title": loc.get("title", ""),
                "address": ", ".join(filter(None, [*(addr.get("addressLines") or []), addr.get("locality", "")])),
                "website": loc.get("websiteUri", ""),
                "phone": (loc.get("phoneNumbers") or {}).get("primaryPhone", ""),
                "maps_uri": (loc.get("metadata") or {}).get("mapsUri", ""),
            })
    return out


DEMO_REVIEW_PREFIX = "demo_"


def link(db: Session, client: Client, conn: GoogleConnection, account: str, location: str, title: str) -> GmbAccount:
    gmb = client.gmb or GmbAccount(tenant_id=client.tenant_id, client_id=client.id, location_id=location)
    client.gmb = gmb
    if not gmb.is_live:
        # Going live: drop this client's simulated reviews and metrics so real Google data isn't mixed with demo data.
        db.execute(delete(Review).where(Review.client_id == client.id, Review.external_review_id.startswith(DEMO_REVIEW_PREFIX)))
        db.execute(delete(MetricDaily).where(MetricDaily.client_id == client.id))
    gmb.connection_id, gmb.google_account, gmb.location_id, gmb.title = conn.id, account, location, title
    gmb.status, gmb.last_error = "connected", ""
    db.flush()
    return gmb


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def sync_reviews(db: Session, client: Client) -> dict:
    gmb = client.gmb
    g = client_for(gmb.connection)
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
    g = client_for(gmb.connection)
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
    except ValueError as e:  # token decryption
        gmb.last_error, gmb.status = str(e), "expired"
        raise api.GoogleApiError(401, str(e))


def publish_reply(client: Client, review_id: str, comment: str) -> None:
    gmb = client.gmb
    client_for(gmb.connection).reply(gmb.google_account, gmb.location_id, review_id, comment)


def publish_post(client: Client, summary: str) -> str:
    gmb = client.gmb
    post = client_for(gmb.connection).create_post(gmb.google_account, gmb.location_id, summary, client.website or None)
    return post.get("name", "")

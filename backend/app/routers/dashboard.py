"""Master Dashboard: agency-wide KPIs (clients, reviews, approvals, content, AI, integrations, leads), what needs
attention now, and a per-client health table. Everything is scoped to the clients the user can see."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import review_queue
from ..ai import ai_enabled, pct
from ..config import settings
from ..db import get_db
from ..metrics import periods, series, totals
from ..models import AuditLog, Client, ContentItem, Keyword, Review, User
from ..security import require_section, visible_client_ids
from ..serializers import client_brief, review_out
from .common import client_names

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

PENDING = ("new", "drafted", "approved", "failed")


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _health(c: Client, reviews: list[Review], content: list[ContentItem], leads_change: int, now: datetime) -> tuple[int, list[str]]:
    """0-100 with the reasons it isn't 100: unanswered/negative/overdue reviews, failed posts, broken connections, falling leads."""
    score, why = 100, []
    waiting = [r for r in reviews if r.reply_status in PENDING]
    neg = sum(r.sentiment == "negative" for r in waiting)
    overdue = sum((now - _aware(r.created_at)) > timedelta(hours=48) for r in waiting)
    failed = sum(i.status == "failed" for i in content)
    if neg:
        score -= min(30, 10 * neg)
        why.append(f"{neg} negative review{'s' if neg > 1 else ''} waiting")
    if overdue:
        score -= min(20, 4 * overdue)
        why.append(f"{overdue} review{'s' if overdue > 1 else ''} over 48h")
    if failed:
        score -= min(20, 10 * failed)
        why.append(f"{failed} failed post{'s' if failed > 1 else ''}")
    if c.gmb and c.gmb.is_live and c.gmb.last_error:
        score -= 15
        why.append("Google sync problem")
    if not (c.gmb and c.gmb.status == "connected"):
        score -= 10
        why.append("Google profile not connected")
    labels = {"facebook": "Facebook", "instagram": "Instagram", "linkedin": "LinkedIn", "youtube": "YouTube", "x": "X"}
    expired = [labels.get(a.platform, a.platform) for a in c.social_accounts if a.status != "connected"]
    if expired:
        score -= 10
        why.append(f"{', '.join(expired)} needs reconnecting")
    if leads_change <= -20:
        score -= 10
        why.append(f"leads down {abs(leads_change)}%")
    return max(0, score), why


@router.get("")
def dashboard(user: User = Depends(require_section("dashboard")), db: Session = Depends(get_db)):
    ids = visible_client_ids(db, user)
    names = client_names(db, user.tenant_id)
    now = datetime.now(timezone.utc)
    month_ago, week_ahead = now - timedelta(days=30), now + timedelta(days=7)
    clients = list(db.scalars(select(Client).where(Client.id.in_(ids)).order_by(Client.company_name)))
    (cs, ce), (ps, pe) = periods(30)
    cur, prev = totals(db, ids, cs, ce), totals(db, ids, ps, pe)

    reviews = list(db.scalars(select(Review).where(Review.client_id.in_(ids))))
    pending = sorted([r for r in reviews if r.reply_status in PENDING], key=lambda r: _aware(r.created_at), reverse=True)
    negative = [r for r in pending if r.sentiment == "negative"]
    recent = [r for r in reviews if _aware(r.created_at) >= month_ago]
    answered = [r for r in recent if r.reply_status == "published" and r.published_at and _aware(r.published_at) >= _aware(r.created_at)]
    content = list(db.scalars(select(ContentItem).where(ContentItem.client_id.in_(ids))))
    seo_alerts = list(db.scalars(select(Keyword).where(Keyword.client_id.in_(ids), Keyword.current_rank - Keyword.previous_rank >= 3)))

    # AI usage (last 30 days) from the audit trail
    ai_rows = list(db.scalars(select(AuditLog).where(AuditLog.tenant_id == user.tenant_id, AuditLog.created_at >= month_ago,
                                                     AuditLog.client_id.in_(ids), AuditLog.entity_type.in_(("review", "content")))))
    drafts = [a for a in ai_rows if a.details and a.details.get("source") in ("ai", "template")]
    tokens = sum(((a.details.get("usage") or {}).get("input") or 0) + ((a.details.get("usage") or {}).get("output") or 0) for a in drafts)

    by_client_reviews: dict[int, list[Review]] = {}
    for r in reviews:
        by_client_reviews.setdefault(r.client_id, []).append(r)
    by_client_content: dict[int, list[ContentItem]] = {}
    for i in content:
        by_client_content.setdefault(i.client_id, []).append(i)

    perf = []
    for c in clients:
        cc, pp = totals(db, [c.id], cs, ce), totals(db, [c.id], ps, pe)
        change = pct(cc["leads"], pp["leads"])
        score, why = _health(c, by_client_reviews.get(c.id, []), by_client_content.get(c.id, []), change, now)
        perf.append({**client_brief(c), "gmb_views": cc["gmb_views"], "leads": cc["leads"], "leads_change_pct": change,
                     "pending_reviews": sum(1 for r in by_client_reviews.get(c.id, []) if r.reply_status in PENDING),
                     "scheduled_posts": sum(1 for i in by_client_content.get(c.id, []) if i.status == "scheduled"),
                     "google_state": review_queue.source_state(c, 0) if c.gmb else "none",
                     "meta_live": any(a.is_live for a in c.social_accounts if a.platform in ("facebook", "instagram")),
                     "health": score, "health_label": "Good" if score >= 80 else "Watch" if score >= 50 else "At risk", "health_reasons": why})
    perf.sort(key=lambda x: (x["health"], -x["pending_reviews"], -x["leads"]))

    google_states = [p["google_state"] for p in perf]
    awaiting_review_approval = [r for r in pending if r.reply_status == "drafted"]
    content_review = [i for i in content if i.status == "in_review"]
    failed_posts = [i for i in content if i.status == "failed"]
    expired_accounts = [(c, a) for c in clients for a in c.social_accounts if a.status != "connected"]

    attention = []
    for i in failed_posts[:5]:
        attention.append({"kind": "failed_post", "severity": "critical", "title": f"Post failed: {i.topic}", "client_id": i.client_id,
                          "client_name": names[i.client_id], "detail": i.last_error[:160], "link": f"/content/?client={i.client_id}&board=failed#c{i.id}"})
    for r in negative[:5]:
        attention.append({"kind": "negative_review", "severity": "serious", "title": f"{r.rating}★ review from {r.author}", "client_id": r.client_id,
                          "client_name": names[r.client_id], "detail": (r.text or "Rating only")[:160], "link": f"/reviews/?client={r.client_id}&filter=negative#r{r.id}"})
    for c, a in expired_accounts[:5]:
        attention.append({"kind": "expired_account", "severity": "warning", "title": f"{a.platform.title()} needs reconnecting", "client_id": c.id,
                          "client_name": c.company_name, "detail": a.last_error[:160] or "Token expired", "link": f"/social/?client={c.id}#meta"})
    for c in clients:
        if c.gmb and c.gmb.last_error and (c.gmb.is_live or c.gmb.has_own_token):
            pending_approval = "quota" in c.gmb.last_error.lower()
            attention.append({"kind": "google", "severity": "warning", "client_id": c.id, "client_name": c.company_name,
                              "title": "Google API approval pending" if pending_approval else "Google sync problem",
                              "detail": c.gmb.last_error[:160], "link": f"/clients/{c.id}/#google"})

    return {
        "kpis": {
            # unchanged keys (mobile app + older pages)
            "active_clients": sum(c.status == "active" for c in clients),
            "onboarding_clients": sum(c.status == "onboarding" for c in clients),
            "gmb_connected": sum(bool(c.gmb and c.gmb.status == "connected") for c in clients),
            "gmb_disconnected": sum(not (c.gmb and c.gmb.status == "connected") for c in clients),
            "pending_reviews": len(pending),
            "negative_reviews": len(negative),
            "scheduled_posts": sum(c.status == "scheduled" for c in content),
            "failed_posts": len(failed_posts),
            "leads": cur["leads"], "leads_change_pct": pct(cur["leads"], prev["leads"]),
            "seo_alerts": len(seo_alerts),
        },
        "master": {
            "clients": {"total": len(clients), "active": sum(c.status == "active" for c in clients),
                        "onboarding": sum(c.status == "onboarding" for c in clients), "paused": sum(c.status == "paused" for c in clients),
                        "at_risk": sum(p["health"] < 50 for p in perf), "watch": sum(50 <= p["health"] < 80 for p in perf)},
            "reviews": {"needs_reply": len(pending), "negative_waiting": len(negative), "new_30d": len(recent),
                        "overdue_48h": sum((now - _aware(r.created_at)) > timedelta(hours=48) for r in pending),
                        "response_rate_30d": round(100 * sum(r.reply_status == "published" for r in recent) / len(recent)) if recent else None,
                        "avg_response_hours_30d": round(sum((_aware(r.published_at) - _aware(r.created_at)).total_seconds() for r in answered) / len(answered) / 3600, 1) if answered else None,
                        "avg_rating_30d": round(sum(r.rating for r in recent) / len(recent), 1) if recent else None,
                        "sample": sum(r.is_sample for r in pending)},
            "approvals": {"replies_waiting": len(awaiting_review_approval), "posts_waiting": len(content_review),
                          "total": len(awaiting_review_approval) + len(content_review)},
            "content": {"drafts": sum(i.status == "draft" for i in content), "in_review": len(content_review),
                        "scheduled_7d": sum(i.status == "scheduled" and i.scheduled_at and _aware(i.scheduled_at) <= week_ahead for i in content),
                        "scheduled": sum(i.status in ("scheduled", "publishing") for i in content),
                        "published_30d": sum(i.status == "published" and i.published_at and _aware(i.published_at) >= month_ago for i in content),
                        "failed": len(failed_posts)},
            "ai": {"enabled": ai_enabled(), "provider": settings.ai_provider, "model": settings.model,
                   "drafts_30d": len(drafts), "ai_drafts_30d": sum(a.details.get("source") == "ai" for a in drafts),
                   "template_drafts_30d": sum(a.details.get("source") == "template" for a in drafts), "tokens_30d": tokens},
            "integrations": {"google_live": google_states.count("live"), "google_approval_pending": google_states.count("approval_pending"),
                             "google_errors": google_states.count("error"),
                             "meta_live_clients": sum(p["meta_live"] for p in perf), "expired_accounts": len(expired_accounts),
                             "scheduler": "celery" if settings.celery_enabled else ("in_process" if settings.scheduler_minutes > 0 else "off")},
            "leads": {"total": cur["leads"], "change_pct": pct(cur["leads"], prev["leads"]), "calls": cur["gmb_calls"],
                      "directions": cur["gmb_directions"], "website_clicks": cur["web_clicks"], "gmb_views": cur["gmb_views"],
                      "gmb_views_change_pct": pct(cur["gmb_views"], prev["gmb_views"])},
        },
        "attention": attention[:12],
        "growth": [{"date": d["date"], "gmb_views": d["gmb_views"], "social_reach": d["social_reach"], "leads": d["leads"]} for d in series(db, ids, cs, ce)],
        "negative_reviews": [review_out(r, names[r.client_id]) for r in negative[:5]],
        "seo_alerts": [{"keyword": k.keyword, "client_name": names[k.client_id], "previous_rank": k.previous_rank, "current_rank": k.current_rank} for k in seo_alerts[:5]],
        "client_performance": perf,
        "lead_sources": {"calls": cur["gmb_calls"], "directions": cur["gmb_directions"], "website_clicks": cur["web_clicks"], "social_engagement": cur["engagement"]},
    }

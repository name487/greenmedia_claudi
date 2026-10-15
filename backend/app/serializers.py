"""Model → JSON dicts. Kept explicit so the API contract used by Django and Flutter is easy to read."""

from datetime import datetime, timezone

from . import adapt
from .google.tokens import expires_at_iso
from .models import AuditLog, Client, ContentItem, Keyword, Report, Review, Task, User
from .security import ROLE_LABELS


def iso(dt):
    """Always emit UTC with an offset; SQLite returns naive datetimes even for timezone-aware columns."""
    if not dt:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def user_out(u: User) -> dict:
    label = getattr(u, "role_label", None) or ROLE_LABELS.get(u.role, u.role)
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "role_label": label, "client_id": u.client_id, "status": u.status,
            "phone": u.phone or ""}


def me_out(u: User, client_name: str | None) -> dict:
    # u must have been through security.load_role (sections/permissions come from the roles table)
    return {**user_out(u), "client_name": client_name, "sections": u.sections, "permissions": u.permissions}


def client_brief(c: Client) -> dict:
    return {
        "id": c.id, "company_name": c.company_name, "industry": c.industry, "city": c.city, "status": c.status, "plan": c.plan,
        "rating": c.gmb.rating if c.gmb else None, "gmb_connected": bool(c.gmb and c.gmb.status == "connected"), "gmb_live": bool(c.gmb and c.gmb.is_live),
        "contact_name": c.contacts[0].name if c.contacts else "",
    }


def contact_out(x) -> dict:
    return {"id": x.id, "name": x.name, "email": x.email, "phone": x.phone, "designation": x.designation, "is_primary": bool(x.is_primary)}


def gmb_out(g) -> dict:
    """The client's Google Business Profile link. Tokens never leave the server; only their state does."""
    return {
        "location_id": g.location_id, "status": g.status, "last_sync": iso(g.last_sync), "rating": g.rating,
        "review_count": g.review_count, "is_live": g.is_live, "title": g.title, "last_error": g.last_error,
        "google_account": g.google_account, "address": g.address, "maps_uri": g.maps_uri,
        "via": "agency" if g.connection_id is not None else ("client" if g.is_live else None),
        "google_email": g.connection.email if g.connection is not None else (g.google_email or None),
        "own_google": {"email": g.google_email, "status": g.token_status or "active", "scopes": g.scopes,
                       "access_token_expires_at": expires_at_iso(g)} if g.refresh_token_enc else None,
    }


def client_out(c: Client) -> dict:
    return {
        **client_brief(c),
        "website": c.website, "services": c.services, "account_manager_id": c.account_manager_id,
        "brand_voice": c.brand_voice, "auto_publish": c.auto_publish, "notes": c.notes,
        "contacts": [contact_out(x) for x in c.contacts],
        "gmb": c.gmb and gmb_out(c.gmb),
        "social_accounts": [{"platform": s.platform, "handle": s.handle, "status": s.status, "is_live": s.is_live, "name": s.name,
                             "last_error": s.last_error} for s in c.social_accounts],
    }


def _utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def review_out(r: Review, client_name: str) -> dict:
    return {
        "id": r.id, "client_id": r.client_id, "client_name": client_name, "author": r.author, "rating": r.rating, "text": r.text,
        "language": r.language, "sentiment": r.sentiment, "reply": r.reply, "reply_status": r.reply_status,
        "needs_escalation": r.rating <= 2, "created_at": iso(r.created_at), "published_at": iso(r.published_at),
        "updated_at": iso(r.updated_at), "edited": bool(r.updated_at and r.created_at and abs((_utc(r.updated_at) - _utc(r.created_at)).total_seconds()) > 60),
        "reviewer_photo": r.reviewer_photo, "is_sample": r.is_sample,
        "reply_source": r.reply_source, "reply_model": r.reply_model, "reply_error": r.reply_error, "drafted_at": iso(r.drafted_at),
        "approved_by": r.approved_by, "approved_at": iso(r.approved_at), "approval_rule": r.approval_rule or "",
        "waiting_hours": round((datetime.now(timezone.utc) - _utc(r.created_at)).total_seconds() / 3600)
        if r.reply_status in ("new", "drafted", "approved", "failed") and r.created_at else None,
    }


def content_out(c: ContentItem, client_name: str) -> dict:
    return {
        "id": c.id, "client_id": c.client_id, "client_name": client_name, "topic": c.topic, "content_type": c.content_type,
        "master_copy": c.master_copy, "hashtags": c.hashtags, "creative_brief": c.creative_brief, "status": c.status,
        "scheduled_at": iso(c.scheduled_at), "created_at": iso(c.created_at), "updated_at": iso(c.updated_at), "published_at": iso(c.published_at),
        "attempts": c.attempts or 0, "next_attempt_at": iso(c.next_attempt_at), "last_error": c.last_error or "",
        "ai_source": c.ai_source or "", "ai_model": c.ai_model or "", "image_url": c.image_url or "",
        "approved_by": c.approved_by, "approved_at": iso(c.approved_at),
        "variants": [{"platform": v.platform, "copy": v.copy, "format": v.format, "external_post_id": v.external_post_id,
                      "status": v.status or "pending", "published_at": iso(v.published_at), "error": v.error or "",
                      "checks": adapt.check(v.platform, v.copy, c.image_url or "") if v.status != "published" else []} for v in c.variants],
    }


def keyword_out(k: Keyword, client_name: str) -> dict:
    return {
        "id": k.id, "client_id": k.client_id, "client_name": client_name, "keyword": k.keyword, "target_url": k.target_url, "location": k.location,
        "current_rank": k.current_rank, "previous_rank": k.previous_rank, "change": k.previous_rank - k.current_rank, "volume": k.volume,
    }


def task_out(t: Task, client_name: str | None, assignee: str | None) -> dict:
    return {
        "id": t.id, "client_id": t.client_id, "client_name": client_name, "assigned_to": t.assigned_to, "assignee_name": assignee,
        "title": t.title, "priority": t.priority, "due_date": t.due_date.isoformat() if t.due_date else None, "status": t.status,
    }


def report_out(r: Report, client_name: str) -> dict:
    return {
        "id": r.id, "client_id": r.client_id, "client_name": client_name, "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(),
        "summary": r.summary, "source": r.source, "created_at": iso(r.created_at), "delivered_at": iso(r.delivered_at), "delivered_via": r.delivered_via,
    }


def audit_out(a: AuditLog, user_name: str | None, client_name: str | None) -> dict:
    return {"id": a.id, "user_name": user_name, "client_id": a.client_id, "client_name": client_name, "action": a.action, "created_at": iso(a.created_at),
            "entity_type": a.entity_type, "entity_id": a.entity_id, "details": a.details or {}}

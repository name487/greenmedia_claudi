"""Model → JSON dicts. Kept explicit so the API contract used by Django and Flutter is easy to read."""

from datetime import timezone

from .models import AuditLog, Client, ContentItem, Keyword, Report, Review, Task, User
from .security import ACTIONS, ROLE_LABELS, SECTIONS


def iso(dt):
    """Always emit UTC with an offset; SQLite returns naive datetimes even for timezone-aware columns."""
    if not dt:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "role_label": ROLE_LABELS[u.role], "client_id": u.client_id}


def me_out(u: User, client_name: str | None) -> dict:
    return {**user_out(u), "client_name": client_name, "sections": SECTIONS[u.role], "permissions": ACTIONS[u.role]}


def client_brief(c: Client) -> dict:
    return {
        "id": c.id, "company_name": c.company_name, "industry": c.industry, "city": c.city, "status": c.status, "plan": c.plan,
        "rating": c.gmb.rating if c.gmb else None, "gmb_connected": bool(c.gmb and c.gmb.status == "connected"), "gmb_live": bool(c.gmb and c.gmb.is_live),
        "contact_name": c.contacts[0].name if c.contacts else "",
    }


def client_out(c: Client) -> dict:
    return {
        **client_brief(c),
        "website": c.website, "services": c.services, "account_manager_id": c.account_manager_id,
        "brand_voice": c.brand_voice, "auto_publish": c.auto_publish, "notes": c.notes,
        "contacts": [{"id": x.id, "name": x.name, "email": x.email, "phone": x.phone, "designation": x.designation} for x in c.contacts],
        "gmb": c.gmb and {"location_id": c.gmb.location_id, "status": c.gmb.status, "last_sync": iso(c.gmb.last_sync), "rating": c.gmb.rating,
                         "review_count": c.gmb.review_count, "is_live": c.gmb.is_live, "title": c.gmb.title, "last_error": c.gmb.last_error,
                         "google_email": c.gmb.connection.email if c.gmb.connection else None},
        "social_accounts": [{"platform": s.platform, "handle": s.handle, "status": s.status} for s in c.social_accounts],
    }


def review_out(r: Review, client_name: str) -> dict:
    return {
        "id": r.id, "client_id": r.client_id, "client_name": client_name, "author": r.author, "rating": r.rating, "text": r.text,
        "language": r.language, "sentiment": r.sentiment, "reply": r.reply, "reply_status": r.reply_status,
        "needs_escalation": r.rating <= 2, "created_at": iso(r.created_at), "published_at": iso(r.published_at),
    }


def content_out(c: ContentItem, client_name: str) -> dict:
    return {
        "id": c.id, "client_id": c.client_id, "client_name": client_name, "topic": c.topic, "content_type": c.content_type,
        "master_copy": c.master_copy, "hashtags": c.hashtags, "creative_brief": c.creative_brief, "status": c.status,
        "scheduled_at": iso(c.scheduled_at), "created_at": iso(c.created_at),
        "variants": [{"platform": v.platform, "copy": v.copy, "format": v.format, "external_post_id": v.external_post_id} for v in c.variants],
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
    return {"id": a.id, "user_name": user_name, "client_id": a.client_id, "client_name": client_name, "action": a.action, "created_at": iso(a.created_at)}

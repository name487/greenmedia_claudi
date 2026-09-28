import calendar
import json
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .api import SESSION_ME, SESSION_TOKEN, Api, ApiError, can, login_required

PLATFORMS = ["gmb", "facebook", "instagram", "linkedin", "youtube", "x"]
CONTENT_TYPES = ["post", "offer", "event", "update"]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _client_filter(request, default=None):
    """Client-portal users are pinned to their company; staff can pick any client (or all)."""
    if request.me.get("client_id"):
        return request.me["client_id"]
    return _int(request.GET.get("client")) or default


def _clients(request):
    return request.api.get("/api/clients")


def _back(request, **params):
    """Redirect to the current page keeping the querystring (PRG pattern)."""
    return HttpResponseRedirect(request.get_full_path())


# ---------- auth ----------

def login_view(request):
    if request.session.get(SESSION_TOKEN):
        return redirect("dashboard")
    ctx = {"demo_users": [
        ("Admin", "Aarav Mehta", "admin@greenmedia.in"), ("Account Manager", "Priya Nair", "priya@greenmedia.in"),
        ("SEO Specialist", "Rohit Verma", "rohit@greenmedia.in"), ("Content Writer", "Sneha Iyer", "sneha@greenmedia.in"),
        ("Designer", "Kabir Shah", "kabir@greenmedia.in"), ("Client", "Dr. Anjali Rao", "anjali@smiledental.in"),
    ]}
    if request.method == "POST":
        try:
            out = Api().post("/api/auth/login", {"email": request.POST.get("email", ""), "password": request.POST.get("password", "")})
        except ApiError as e:
            ctx.update(error=e.detail, email=request.POST.get("email", ""))
            return render(request, "portal/login.html", ctx, status=401 if e.status == 401 else 502)
        request.session.cycle_key()
        request.session[SESSION_TOKEN] = out["access_token"]
        request.session[SESSION_ME] = out["user"]
        nxt = request.GET.get("next", "/")
        return redirect(nxt if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) else "/")
    return render(request, "portal/login.html", ctx)


@require_POST
def logout_view(request):
    request.session.flush()
    return redirect("login")


# ---------- dashboard ----------

@login_required("dashboard")
def dashboard(request):
    d = request.api.get("/api/dashboard")
    hour = timezone.localtime().hour
    greeting = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    src = d["lead_sources"]
    return render(request, "portal/dashboard.html", {
        "d": d, "k": d["kpis"], "greeting": greeting,
        "lead_sources": [("Calls from Google", src["calls"]), ("Direction requests", src["directions"]), ("Website clicks", src["website_clicks"]), ("Social engagement", src["social_engagement"])],
    })


# ---------- clients ----------

@login_required("clients")
def clients(request):
    f = {k: request.GET.get(k, "") for k in ("q", "industry", "status", "service")}
    if request.method == "POST" and can(request, "client.edit"):
        c = request.api.post("/api/clients", {k: request.POST.get(k, "") for k in ("company_name", "website", "industry", "city", "plan", "contact_name", "contact_email", "contact_phone")})
        messages.success(request, f"{c['company_name']} added.")
        return redirect("client_detail", client_id=c["id"])
    rows = request.api.get("/api/clients", **f)
    return render(request, "portal/clients.html", {"rows": rows, "f": f, "facets": request.api.get("/api/clients/facets"), "plans": ["Starter", "Growth", "Pro", "Agency"]})


@login_required("clients")
def client_detail(request, client_id):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "notes":
            request.api.patch(f"/api/clients/{client_id}", {"notes": request.POST.get("notes", "")})
            messages.success(request, "Notes saved.")
        elif action == "auto_publish":
            keys = request.POST.getlist("channels")
            request.api.patch(f"/api/clients/{client_id}", {"auto_publish": {k: (k in request.POST.getlist("on")) for k in keys}})
            messages.success(request, "Publishing safety updated.")
        elif action == "status":
            request.api.patch(f"/api/clients/{client_id}", {"status": request.POST.get("status")})
        return _back(request)
    c = request.api.get(f"/api/clients/{client_id}")
    channels = ["reviews", "gmb"] + [s["platform"] for s in c["social_accounts"]]
    return render(request, "portal/client_detail.html", {"c": c, "k": c["kpis"], "channels": channels, "editable": can(request, "client.edit")})


# ---------- GMB ----------

@login_required("gmb")
def gmb(request):
    cl = _clients(request)
    cid = _client_filter(request, cl[0]["id"])
    if request.method == "POST":
        out = request.api.post(f"/api/clients/{cid}/gmb/sync")
        if "sync" in out:
            s = out["sync"]
            messages.success(request, f"Synced from Google: {s['new_reviews']} new reviews, {s['total_on_google']} total on Google"
                                      + (f", {s['metric_days']} days of insights." if "metric_days" in s else "."))
            if s.get("metrics_error"):
                messages.warning(request, f"Insights not updated: {s['metrics_error']}")
        else:
            messages.success(request, "Profile synced (demo data — link a real Google location to go live).")
        return _back(request)
    c = request.api.get(f"/api/clients/{cid}")
    insights = request.api.get(f"/api/clients/{cid}/insights", days=45)
    posts = [x for x in c["content"] if any(v["platform"] == "gmb" for v in x["variants"])]
    k = c["kpis"]
    return render(request, "portal/gmb.html", {
        "clients": cl, "cid": cid, "c": c, "k": k, "series": insights, "posts": posts,
        "unanswered": sum(r["reply_status"] != "published" for r in c["reviews"]),
        "actions": [("Website clicks", k["web_clicks"]["current"]), ("Direction requests", k["gmb_directions"]["current"]), ("Phone calls", k["gmb_calls"]["current"])],
    })


# ---------- Google Business Profile connections ----------

@login_required("gmb")
def google_connections(request):
    result = request.GET.get("google", "")
    if result.startswith("connected:"):
        messages.success(request, f"Connected {result.split(':', 1)[1]}. Now link its locations to clients below.")
    elif result.startswith("error:"):
        messages.error(request, f"Google connection failed: {result.split(':', 1)[1]}")
    if result:
        return redirect("google")  # drop the query string so a refresh doesn't repeat the message

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "connect":
            return ShareRedirect(request.api.post("/api/google/connect")["auth_url"])
        if action == "link":
            out = request.api.post("/api/google/link", {
                "client_id": _int(request.POST.get("client_id")), "connection_id": _int(request.POST.get("connection_id")),
                "account": request.POST["account"], "location": request.POST["location"], "title": request.POST.get("title", ""),
            })
            if "sync_error" in out:
                messages.warning(request, f"Linked, but the first sync failed: {out['sync_error']}")
            else:
                s = out["sync"]
                messages.success(request, f"Linked and synced: {s['new_reviews']} reviews imported ({s['total_on_google']} on Google).")
        elif action == "unlink":
            request.api.post("/api/google/unlink", {"client_id": _int(request.POST.get("client_id"))})
            messages.success(request, "Location unlinked — the client is back on demo data.")
        elif action == "disconnect":
            request.api.delete(f"/api/google/connections/{_int(request.POST.get('connection_id'))}")
            messages.success(request, "Google account disconnected and access revoked.")
        return redirect("google")

    can_manage = can(request, "client.edit")
    status = request.api.get("/api/google/status") if can_manage else None
    locations, loc_errors = [], []
    if status and status["configured"] and any(c["status"] == "active" for c in status["connections"]):
        data = request.api.get("/api/google/locations")
        locations, loc_errors = data["locations"], data["errors"]
    return render(request, "portal/google.html", {
        "status": status, "locations": locations, "loc_errors": loc_errors, "clients": _clients(request), "can_manage": can_manage,
    })


# ---------- reviews ----------

@login_required("reviews")
def reviews(request):
    if request.method == "POST":
        rid, action = request.POST.get("review_id"), request.POST.get("action")
        if action == "sync":
            r = request.api.post("/api/reviews/sync", {"client_id": _client_filter(request)})
            if r["mode"] == "live":
                messages.success(request, f"Pulled {r['new_reviews']} new review(s) from {r['profiles']} live Google profile(s).")
                for err in r["errors"]:
                    messages.error(request, err)
            else:
                messages.success(request, f"Demo: new {r['rating']}★ review for {r['client_name']} — {'auto-published' if r['reply_status'] == 'published' else 'AI draft ready'}.")
        elif action == "save":
            request.api.patch(f"/api/reviews/{rid}", {"reply": request.POST.get("reply", "")})
            messages.success(request, "Reply saved.")
        elif action in ("draft",):
            request.api.post(f"/api/reviews/{rid}/draft")
        elif action in ("approve", "reject", "publish", "reopen"):
            if action in ("approve", "publish") and request.POST.get("reply") is not None and request.POST.get("reply") != request.POST.get("original"):
                request.api.patch(f"/api/reviews/{rid}", {"reply": request.POST["reply"]})
            request.api.post(f"/api/reviews/{rid}/{action}")
            if action == "publish":
                messages.success(request, "Reply published to Google.")
        return _back(request)
    flt = request.GET.get("filter", "pending")
    cid = _client_filter(request)
    data = request.api.get("/api/reviews", filter=flt, client_id=cid)
    tabs = [("pending", "Needs reply"), ("approved", "Approved"), ("negative", "Negative"), ("published", "Published"), ("all", "All")]
    return render(request, "portal/reviews.html", {
        "items": data["items"], "counts": data["counts"], "tabs": tabs, "flt": flt, "cid": cid,
        "clients": None if request.me.get("client_id") else _clients(request),
        "can_publish": can(request, "review.publish"), "can_approve": can(request, "review.approve"),
    })


# ---------- content ----------

def _local_default_schedule():
    t = timezone.localtime() + timedelta(days=1)
    return t.replace(hour=10, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def _aware(value: str):
    dt = datetime.fromisoformat(value)
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


@login_required("content")
def content(request):
    cl = _clients(request)
    brief_cid = _int(request.POST.get("client_id") or request.GET.get("client")) or cl[0]["id"]
    if request.me.get("client_id"):
        brief_cid = request.me["client_id"]
    ctx = {"clients": cl, "brief_cid": brief_cid, "types": CONTENT_TYPES, "when": _local_default_schedule(), "topic": "", "ctype": "post", "selected": ["gmb"]}

    if request.method == "POST":
        action = request.POST.get("action")
        if action in ("submit", "request_changes", "approve", "publish"):
            request.api.post(f"/api/content/{request.POST['content_id']}/{action}")
            messages.success(request, {"submit": "Sent for approval.", "request_changes": "Sent back to draft.", "approve": "Approved and scheduled.", "publish": "Published."}[action])
            return _back(request)
        topic, ctype, selected = request.POST.get("topic", "").strip(), request.POST.get("content_type", "post"), request.POST.getlist("platforms")
        ctx.update(topic=topic, ctype=ctype, selected=selected, when=request.POST.get("scheduled_at") or ctx["when"])
        if action == "generate":
            try:
                ctx["draft"] = request.api.post("/api/content/generate", {"client_id": brief_cid, "topic": topic, "content_type": ctype, "platforms": selected})
            except ApiError as e:
                messages.error(request, e.detail)
        elif action in ("save_draft", "save_review", "save_schedule"):
            variants = [{"platform": p, "copy": request.POST.get(f"copy_{p}", ""), "format": request.POST.get(f"format_{p}", "1:1")} for p in request.POST.getlist("variant_platforms")]
            status = {"save_draft": "draft", "save_review": "in_review", "save_schedule": "scheduled"}[action]
            body = {"client_id": brief_cid, "topic": topic, "content_type": ctype, "master_copy": request.POST.get("master_copy", ""),
                    "hashtags": json.loads(request.POST.get("hashtags") or "[]"), "creative_brief": request.POST.get("creative_brief", ""),
                    "variants": variants, "status": status, "scheduled_at": _aware(request.POST["scheduled_at"]).isoformat() if request.POST.get("scheduled_at") else None}
            try:
                request.api.post("/api/content", body)
                messages.success(request, {"draft": "Draft saved.", "in_review": "Sent for approval.", "scheduled": "Approved and scheduled."}[status])
                return redirect(f"{reverse('content')}?client={brief_cid}")
            except ApiError as e:
                messages.error(request, e.detail)
                ctx["draft"] = {"master_copy": body["master_copy"], "hashtags": body["hashtags"], "creative_brief": body["creative_brief"], "variants": variants, "source": "edited"}

    meta = request.api.get(f"/api/content/platforms/{brief_cid}")
    pipeline_cid = _client_filter(request)
    ctx.update(
        platforms=meta["platforms"], brand_voice=meta["brand_voice"], can_schedule=meta["can_schedule"],
        can_create=can(request, "content.create"), can_publish=can(request, "content.publish"),
        items=request.api.get("/api/content", client_id=pipeline_cid), pipeline_cid=pipeline_cid,
    )
    if ctx.get("draft"):
        ctx["draft_hashtags_json"] = json.dumps(ctx["draft"].get("hashtags", []))
    return render(request, "portal/content.html", ctx)


# ---------- creative ----------

@login_required("creative")
def creative(request):
    cl = _clients(request)
    cid = _client_filter(request, cl[0]["id"])
    c = next(x for x in cl if x["id"] == cid)
    detail = request.api.get(f"/api/clients/{cid}")
    return render(request, "portal/creative.html", {
        "clients": cl, "cid": cid, "c": c, "headline": request.GET.get("headline", "Your headline here"), "cta": detail["brand_voice"].get("cta_style", "Contact us"),
        "sizes": [("Instagram feed", "4:5", 1080, 1350), ("Instagram / FB square", "1:1", 1080, 1080), ("Story / Reel", "9:16", 1080, 1920),
                  ("Google Business post", "4:3", 1200, 900), ("LinkedIn / link share", "1.91:1", 1200, 627), ("YouTube thumbnail", "16:9", 1280, 720)],
    })


# ---------- social ----------

@login_required("social")
def social(request):
    if request.method == "POST":
        if request.POST.get("action") == "reconnect":
            request.api.post(f"/api/clients/{request.POST['client_id']}/social/{request.POST['platform']}/reconnect")
            messages.success(request, "Account reconnected.")
        else:
            request.api.post(f"/api/content/{request.POST['content_id']}/{request.POST['action']}")
            messages.success(request, "Updated.")
        return _back(request)
    today = timezone.localdate()
    try:
        month = date.fromisoformat(request.GET.get("month", "") + "-01")
    except ValueError:
        month = today.replace(day=1)
    cid = _client_filter(request)
    items = request.api.get("/api/content", client_id=cid)
    by_day: dict[date, list] = {}
    for it in items:
        if it["scheduled_at"]:
            d = timezone.localtime(datetime.fromisoformat(it["scheduled_at"])).date()
            by_day.setdefault(d, []).append(it)
    weeks = [[{"date": d, "other": d.month != month.month, "today": d == today, "posts": by_day.get(d, [])} for d in wk]
             for wk in calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month)]
    cl = _clients(request)
    accounts = []
    for c in cl if not cid else [x for x in cl if x["id"] == cid]:
        for s in request.api.get(f"/api/clients/{c['id']}")["social_accounts"]:
            accounts.append({**s, "client_id": c["id"], "client_name": c["company_name"]})
    prev_m = (month - timedelta(days=1)).replace(day=1)
    next_m = (month + timedelta(days=32)).replace(day=1)
    return render(request, "portal/social.html", {
        "weeks": weeks, "month": month, "prev_m": prev_m.strftime("%Y-%m"), "next_m": next_m.strftime("%Y-%m"), "cid": cid,
        "queue": [i for i in items if i["status"] != "published"], "accounts": accounts, "broken": [a for a in accounts if a["status"] != "connected"],
        "clients": None if request.me.get("client_id") else cl, "can_publish": can(request, "content.publish"),
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    })


# ---------- SEO ----------

@login_required("seo")
def seo(request):
    cid = _client_filter(request)
    if request.method == "POST" and cid:
        request.api.post("/api/seo/keywords", {"client_id": cid, "keyword": request.POST.get("keyword", "")})
        messages.success(request, "Keyword added — ranking appears after the next rank check.")
        return _back(request)
    sort = request.GET.get("sort", "change")
    d = request.api.get("/api/seo", client_id=cid, sort=sort)
    return render(request, "portal/seo.html", {"d": d, "s": d["summary"], "cid": cid, "sort": sort, "clients": _clients(request)})


# ---------- analytics ----------

@login_required("analytics")
def analytics(request):
    cid = _client_filter(request)
    days = _int(request.GET.get("days")) or 30
    if days not in (7, 30, 45):
        days = 30
    d = request.api.get("/api/analytics", client_id=cid, days=days)
    t = d["totals"]
    actions = {k: t["gmb_calls"][k] + t["gmb_directions"][k] + t["web_clicks"][k] for k in ("current", "previous")}
    actions["change_pct"] = round((actions["current"] - actions["previous"]) / actions["previous"] * 100) if actions["previous"] else 0
    for row in d["series"]:
        row["gmb_actions"] = row["gmb_calls"] + row["gmb_directions"] + row["web_clicks"]
    return render(request, "portal/analytics.html", {
        "d": d, "t": t, "actions": actions, "cid": cid, "days": days, "clients": None if request.me.get("client_id") else _clients(request),
        "sources": [("Google calls", t["gmb_calls"]["current"]), ("Directions", t["gmb_directions"]["current"]), ("Website clicks", t["web_clicks"]["current"]), ("Form & WhatsApp leads", t["leads"]["current"])],
        "top": [(x["client_name"], x["leads"]) for x in d.get("top_clients", [])],
    })


# ---------- reports ----------

class ShareRedirect(HttpResponseRedirect):
    allowed_schemes = ["https", "mailto"]


KPI_LABELS = [("gmb_views", "GMB profile views"), ("gmb_calls", "Calls"), ("gmb_directions", "Direction requests"), ("web_clicks", "Website clicks"),
              ("organic_sessions", "Organic sessions"), ("social_reach", "Social reach"), ("engagement", "Engagement"), ("leads", "Leads")]


@login_required("reports")
def reports(request):
    cl = None if request.me.get("client_id") else _clients(request)
    cid = _client_filter(request, cl[0]["id"] if cl else None)
    if request.method == "POST":
        if request.POST.get("action") == "generate":
            r = request.api.post("/api/reports/generate", {"client_id": cid})
            messages.success(request, "Report generated." + (" (Offline template — add an AI key on the API server for AI narratives.)" if r["source"] == "template" else ""))
            return redirect(f"{reverse('reports')}?client={cid}&report={r['id']}")
        out = request.api.post(f"/api/reports/{request.POST['report_id']}/deliver", {"via": request.POST["action"]})
        return ShareRedirect(out["share_url"])  # opens the mail client / WhatsApp with the report pre-filled
    lst = request.api.get("/api/reports", client_id=cid)
    rid = _int(request.GET.get("report")) or (lst[0]["id"] if lst else None)
    rep = request.api.get(f"/api/reports/{rid}") if rid else None
    return render(request, "portal/reports.html", {
        "clients": cl, "cid": cid, "reports": lst, "rep": rep, "can_deliver": can(request, "report.deliver"),
        "kpi_rows": [(label, rep["kpis"][k]) for k, label in KPI_LABELS] if rep else [],
        "client_name": rep["client_name"] if rep else next((c["company_name"] for c in (cl or []) if c["id"] == cid), request.me.get("client_name")),
    })


# ---------- tasks ----------

@login_required("tasks")
def tasks(request):
    if request.method == "POST":
        if request.POST.get("action") == "create":
            request.api.post("/api/tasks", {"title": request.POST.get("title", ""), "client_id": _int(request.POST.get("client_id")), "assigned_to": _int(request.POST.get("assigned_to")),
                                            "priority": request.POST.get("priority", "medium"), "due_date": request.POST.get("due_date") or None})
            messages.success(request, "Task created.")
        else:
            request.api.patch(f"/api/tasks/{request.POST['task_id']}", {"status": request.POST["status"]})
        return _back(request)
    cid = _client_filter(request)
    mine = request.GET.get("mine") == "1"
    items = request.api.get("/api/tasks", client_id=cid, mine="true" if mine else None)
    cols = [("todo", "To do"), ("in_progress", "In progress"), ("review", "Review"), ("done", "Done")]
    return render(request, "portal/tasks.html", {
        "columns": [(key, label, [t for t in items if t["status"] == key]) for key, label in cols], "statuses": cols,
        "cid": cid, "mine": mine, "clients": _clients(request), "staff": request.api.get("/api/auth/users"),
        "audit": request.api.get("/api/audit", client_id=cid, limit=30), "due": (timezone.localdate() + timedelta(days=3)).isoformat(),
    })


# ---------- settings ----------

@login_required("settings")
def settings_view(request):
    if request.method == "POST":
        request.api.patch("/api/settings", {"notify_on_negative_review": "notify" in request.POST, "require_client_approval": "client_approval" in request.POST})
        messages.success(request, "Settings saved.")
        return _back(request)
    s = request.api.get("/api/settings")
    health = request.api.get("/api/health")
    matrix = [(sec, [sec in r["sections"] for r in s["roles"]]) for sec in s["sections"]]
    return render(request, "portal/settings.html", {"s": s, "health": health, "matrix": matrix, "can_edit": can(request, "settings.edit")})

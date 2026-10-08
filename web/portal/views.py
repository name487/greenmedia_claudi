import calendar
import json
from datetime import date, datetime, timedelta
from urllib.parse import quote

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .api import SESSION_ME, SESSION_TOKEN, Api, ApiError, can, login_required
from .templatetags import gm

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


def _no_clients(request, title: str):
    """Fresh installs (SEED_DEMO=0) start with no clients; per-client pages show a prompt instead of crashing."""
    return render(request, "portal/no_clients.html", {"title": title})


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
    try:  # only offer the one-tap demo accounts when the API seeds demo data
        ctx["demo"] = bool(Api().get("/api/health").get("demo"))
    except ApiError:
        ctx["demo"] = False
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

FILTER_KEYS = ("q", "industry", "status", "service", "plan", "manager_id", "sort")
DEFAULT_SERVICES = ["GMB Management", "Review Management"]


def _client_body(post) -> dict:
    """Fields shared by the Add client and Edit details forms."""
    return {
        "company_name": post.get("company_name", "").strip(), "website": post.get("website", "").strip(),
        "industry": post.get("industry", "").strip(), "city": post.get("city", "").strip(),
        "plan": post.get("plan", "Starter"), "status": post.get("status", "onboarding"),
        "services": post.getlist("services"), "account_manager_id": _int(post.get("account_manager_id")),
    }


@login_required("clients")
def clients(request):
    f = {k: request.GET.get(k, "") for k in FILTER_KEYS}
    if request.method == "POST" and can(request, "client.edit") and request.POST.get("action") == "import":
        upload = request.FILES.get("csv_file")
        if not upload:
            messages.error(request, "Choose a CSV file to import.")
        elif upload.size > 5_000_000:
            messages.error(request, "That file is over 5 MB — split it into smaller files.")
        else:
            try:
                text = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                messages.error(request, "The file isn't UTF-8 text. In Excel use Save As → “CSV UTF-8 (Comma delimited)”.")
                return redirect("clients")
            out = request.api.post("/api/clients/import", {"csv": text})  # row errors surface as a flash message
            messages.success(request, f"Imported {out['created']} client(s)."
                             + (f" Skipped {len(out['skipped'])} that already exist: {', '.join(out['skipped'][:10])}{'…' if len(out['skipped']) > 10 else ''}." if out["skipped"] else ""))
        return redirect("clients")
    if request.method == "POST" and can(request, "client.edit"):
        body = {**_client_body(request.POST), **{k: request.POST.get(k, "").strip() for k in ("contact_name", "contact_email", "contact_phone")}}
        c = request.api.post("/api/clients", body)
        messages.success(request, f"{c['company_name']} added.")
        return redirect("client_detail", client_id=c["id"])
    rows = request.api.get("/api/clients", **{k: v for k, v in f.items() if k != "sort" or v})
    return render(request, "portal/clients.html", {
        "rows": rows, "f": f, "facets": request.api.get("/api/clients/facets"), "default_services": DEFAULT_SERVICES,
        "filtered": any(f[k] for k in FILTER_KEYS if k != "sort"),
    })


@login_required("clients")
def clients_template(request):
    resp = HttpResponse(request.api._request_text("/api/clients/import/template"), content_type="text/csv")
    resp["Content-Disposition"] = "attachment; filename=clients-template.csv"
    return resp


def _google_result(request, result: str) -> None:
    """Show the outcome of Google's consent screen (the API's callback redirects here with ?google=...)."""
    kind, _, detail = result.partition(":")
    if kind == "linked":
        messages.success(request, f"Google connected and “{detail}” linked. Reviews, rating and insights are now live.")
    elif kind == "reconnected":
        messages.success(request, f"Google reconnected as {detail}. Syncing continues with the fresh sign-in.")
    elif kind == "connected":
        messages.success(request, f"Signed in to Google as {detail}. Choose which Business Profile location belongs to this client.")
    elif kind == "error":
        messages.error(request, f"Google connection failed: {detail}")


def _google_action(request, client_id, action: str):
    base = f"/api/clients/{client_id}/google"
    here = reverse("client_detail", args=[client_id])
    if action == "google_connect":
        return ShareRedirect(request.api.post(f"{base}/connect")["auth_url"])
    if action == "google_link":
        out = request.api.post(f"{base}/link", {"connection_id": _int(request.POST.get("connection_id")),
                                                "account": request.POST.get("account", ""), "location": request.POST.get("location", "")})
        if "sync_error" in out:
            messages.warning(request, f"Linked “{out['gmb']['title']}”, but the first sync failed: {out['sync_error']}")
        else:
            messages.success(request, f"Linked “{out['gmb']['title']}”: {out['sync']['new_reviews']} reviews imported ({out['sync']['total_on_google']} on Google).")
    elif action == "google_sync":
        out = request.api.post(f"/api/clients/{client_id}/gmb/sync")
        if "sync" in out:
            s = out["sync"]
            messages.success(request, f"Synced from Google: {s['new_reviews']} new reviews, {s['total_on_google']} on Google.")
            if s.get("metrics_error"):
                messages.warning(request, f"Insights not updated: {s['metrics_error']}")
    elif action == "google_refresh":
        out = request.api.post(f"{base}/refresh")
        messages.success(request, f"Google connection works. New access token valid until {gm.when(out['access_token_expires_at'])}.")
    elif action == "google_unlink":
        request.api.post(f"{base}/unlink")
        messages.success(request, "Location unlinked — this client is back on demo data.")
    elif action == "google_disconnect":
        request.api.delete(base)
        messages.success(request, "Client's Google sign-in removed and access revoked.")
    return HttpResponseRedirect(here + "#google")


@login_required("clients")
def client_detail(request, client_id):
    result = request.GET.get("google", "")
    if result:
        _google_result(request, result)
        # Drop ?google= so a refresh doesn't repeat it; open the location picker when there is a choice to make
        return HttpResponseRedirect(reverse("client_detail", args=[client_id]) + ("?pick=1#google" if result.startswith("connected:") else "#google"))
    if request.method == "POST":
        action = request.POST.get("action", "")
        contacts = f"/api/clients/{client_id}/contacts"
        if action.startswith("google_"):
            return _google_action(request, client_id, action)
        if action == "brand_voice":
            lines = lambda k: [x.strip() for x in request.POST.get(k, "").splitlines() if x.strip()]  # noqa: E731
            request.api.patch(f"/api/clients/{client_id}", {"brand_voice": {
                **{k: request.POST.get(k, "").strip() for k in ("tone", "sign_off", "cta_style", "review_prompt", "escalation_rule")},
                "reply_length": request.POST.get("reply_length") or "medium",
                "preferred_phrases": lines("preferred_phrases"), "prohibited_claims": lines("prohibited_claims"),
                "languages": [x.strip() for x in request.POST.get("languages", "").split(",") if x.strip()],
            }})
            messages.success(request, "Brand voice saved. New AI drafts for this client use it.")
            return HttpResponseRedirect(reverse("client_detail", args=[client_id]) + "#voice")
        if action == "brand_voice_try":
            body = {"rating": _int(request.POST.get("rating")) or 5, "text": request.POST.get("text", ""), "author": request.POST.get("author", "").strip() or "Priya Sharma"}
            out = request.api.post(f"/api/clients/{client_id}/brand-voice/try", body)
            request.session["voice_try"] = {**body, "reply": out["reply"], "ai": out["ai"], "client_id": client_id}
            return HttpResponseRedirect(reverse("client_detail", args=[client_id]) + "#voice-try")
        if action == "profile":
            request.api.patch(f"/api/clients/{client_id}", _client_body(request.POST))
            messages.success(request, "Client details saved.")
        elif action == "notes":
            request.api.patch(f"/api/clients/{client_id}", {"notes": request.POST.get("notes", "")})
            messages.success(request, "Notes saved.")
        elif action == "auto_publish":
            keys = request.POST.getlist("channels")
            request.api.patch(f"/api/clients/{client_id}", {"auto_publish": {k: (k in request.POST.getlist("on")) for k in keys}})
            messages.success(request, "Publishing safety updated.")
        elif action == "status":
            request.api.patch(f"/api/clients/{client_id}", {"status": request.POST.get("status")})
        elif action == "add_contact":
            x = request.api.post(contacts, {k: request.POST.get(k, "").strip() for k in ("name", "email", "phone", "designation")} | {"is_primary": "is_primary" in request.POST})
            messages.success(request, f"Added {x['name']}.")
            return HttpResponseRedirect(reverse("client_detail", args=[client_id]) + "#contacts")
        elif action == "update_contact":
            x = request.api.patch(f"{contacts}/{_int(request.POST.get('contact_id'))}", {k: request.POST.get(k, "").strip() for k in ("name", "email", "phone", "designation")})
            messages.success(request, f"Saved {x['name']}.")
            return HttpResponseRedirect(reverse("client_detail", args=[client_id]) + "#contacts")
        elif action == "primary_contact":
            x = request.api.patch(f"{contacts}/{_int(request.POST.get('contact_id'))}", {"is_primary": True})
            messages.success(request, f"{x['name']} is now the primary contact.")
            return HttpResponseRedirect(reverse("client_detail", args=[client_id]) + "#contacts")
        elif action == "delete_contact":
            request.api.delete(f"{contacts}/{_int(request.POST.get('contact_id'))}")
            messages.success(request, "Contact removed.")
            return HttpResponseRedirect(reverse("client_detail", args=[client_id]) + "#contacts")
        elif action == "delete_client":
            out = request.api.delete(f"/api/clients/{client_id}?confirm_name={quote(request.POST.get('confirm_name', ''))}")
            msg = "Client deleted."
            if out["disabled_portal_users"]:
                msg += f" Disabled portal login(s): {', '.join(out['disabled_portal_users'])}."
            messages.success(request, msg)
            return redirect("clients")
        return _back(request)
    c = request.api.get(f"/api/clients/{client_id}")
    channels = ["reviews", "gmb"] + [s["platform"] for s in c["social_accounts"]]
    editable = can(request, "client.edit")
    google = request.api.get(f"/api/clients/{client_id}/google")
    voice_try = request.session.pop("voice_try", None)
    if voice_try and voice_try.get("client_id") != client_id:
        voice_try = None
    locations = None
    p = google["profile"] or {}
    # Listing locations calls Google, so only when choosing (or when signed in but nothing is linked yet)
    if editable and google["configured"] and (request.GET.get("pick") or (p.get("own_google") and not p.get("is_live"))):
        locations = request.api.get(f"/api/clients/{client_id}/google/locations")
    return render(request, "portal/client_detail.html", {
        "c": c, "k": c["kpis"], "channels": channels, "editable": editable,
        "facets": request.api.get("/api/clients/facets") if editable else None,
        "google": google, "g": p, "locations": locations,
        "voice": request.api.get(f"/api/clients/{client_id}/brand-voice"), "voice_try": voice_try,
        "lengths": [("short", "Short (1-2 sentences)"), ("medium", "Medium (2-4 sentences)"), ("long", "Long (4-6 sentences)")],
    })


# ---------- GMB ----------

@login_required("gmb")
def gmb(request):
    cl = _clients(request)
    if not cl:
        return _no_clients(request, "GMB Center")
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
    # Google returns the browser to WEB_APP_URL. If that is a different origin (e.g. localhost vs 127.0.0.1),
    # the browser arrives without this session and the result appears to vanish.
    here = f"{request.scheme}://{request.get_host()}"
    wrong_host = bool(status and status.get("web_app_url") and status["web_app_url"].rstrip("/") != here)
    diag = request.api.get("/api/google/diagnostics", live=request.GET.get("live")) if can_manage else None
    return render(request, "portal/google.html", {
        "status": status, "locations": locations, "loc_errors": loc_errors, "clients": _clients(request), "can_manage": can_manage,
        "here": here, "wrong_host": wrong_host, "diag": diag,
    })


# ---------- reviews ----------

QUEUE_FILTERS = ("rating", "sentiment", "source", "q", "sort")
PAGE = 30


def _sync_messages(request, out: dict) -> None:
    parts = []
    if out["profiles"]:
        parts.append(f"{out['new_reviews']} new review(s) from {out['profiles']} Google profile(s)")
    if out["sample_reviews"]:
        parts.append(f"{out['sample_reviews']} sample review(s)")
    msg = "Synced: " + (" and ".join(parts) or "nothing new") + "."
    if out["drafted"]:
        msg += f" AI drafted {out['drafted']} repl{'y' if out['drafted'] == 1 else 'ies'}"
        msg += f", {out['auto_published']} auto-published." if out["auto_published"] else "."
    messages.success(request, msg)
    if out["approval_pending"]:
        messages.warning(request, f"Google API approval pending for {', '.join(out['approval_pending'])} — "
                                  + ("showing sample reviews until Google approves." if out["sample_reviews"] else "no reviews can be fetched yet."))
    for err in out["errors"]:
        messages.error(request, err)


@login_required("reviews")
def reviews(request):
    if request.method == "POST":
        rid, action = request.POST.get("review_id"), request.POST.get("action", "")
        if action == "sync":
            _sync_messages(request, request.api.post("/api/reviews/sync", {"client_id": _client_filter(request)}))
        elif action.startswith("bulk_"):
            ids = [i for i in map(_int, request.POST.getlist("ids")) if i]
            if not ids:
                messages.warning(request, "Select at least one review first.")
            else:
                verb = action.removeprefix("bulk_")
                out = request.api.post("/api/reviews/bulk", {"ids": ids, "action": verb})
                label = {"draft": "AI-drafted", "approve": "Approved", "publish": "Published", "reject": "Rejected"}[verb]
                if out["done"]:
                    messages.success(request, f"{label} {out['done']} review(s).")
                for f in out["failed"][:5]:
                    messages.error(request, f"Review #{f['id']}: {f['error']}")
                if len(out["failed"]) > 5:
                    messages.error(request, f"…and {len(out['failed']) - 5} more not done.")
        elif action == "save":
            request.api.patch(f"/api/reviews/{rid}", {"reply": request.POST.get("reply", "")})
            messages.success(request, "Reply saved.")
        elif action == "draft":
            out = request.api.post(f"/api/reviews/{rid}/draft", {"instruction": request.POST.get("instruction", "").strip()})
            if out["source"] == "ai":
                messages.success(request, f"AI reply drafted with {out['ai']['model']}.")
            else:
                messages.warning(request, f"Drafted from the brand-voice template — AI not used: {out['ai'].get('error', '')} {out['ai'].get('hint', '')}".strip())
        elif action in ("approve", "reject", "publish", "reopen"):
            if action in ("approve", "publish") and request.POST.get("reply") is not None and request.POST.get("reply") != request.POST.get("original"):
                request.api.patch(f"/api/reviews/{rid}", {"reply": request.POST["reply"]})
            out = request.api.post(f"/api/reviews/{rid}/{action}")
            if action == "publish":
                messages.success(request, "Marked as published — sample review, nothing was sent to Google." if out["is_sample"] else "Reply published to Google.")
        return _back(request)
    flt = request.GET.get("filter", "pending")
    cid = _client_filter(request)
    f = {k: request.GET.get(k, "") for k in QUEUE_FILTERS}
    limit = min(max(_int(request.GET.get("limit")) or PAGE, PAGE), 200)
    # Not api.get(): it drops "all" values (meant for client pickers), which would turn the All tab into Needs reply
    params = {"filter": flt, "limit": limit, **({"client_id": cid} if cid else {}), **{k: v for k, v in f.items() if v}}
    data = request.api._request("GET", "/api/reviews", params=params)
    tabs = [("pending", "Needs reply"), ("approved", "Approved"), ("negative", "Negative"), ("published", "Published"), ("all", "All")]
    src = data["sources"]
    single = src["clients"][0] if len(src["clients"]) == 1 else None
    return render(request, "portal/reviews.html", {
        "items": data["items"], "counts": data["counts"], "total": data["total"], "stats": data["stats"], "sources": src, "single": single,
        "tabs": tabs, "flt": flt, "cid": cid, "f": f, "filtered": any(f[k] for k in ("rating", "sentiment", "source", "q")),
        "more": limit + PAGE if data["total"] > limit else None,
        "clients": None if request.me.get("client_id") else _clients(request),
        "can_publish": can(request, "review.publish"), "can_approve": can(request, "review.approve"),
        "can_sync": "gmb" in request.me.get("sections", []),
    })


# ---------- content ----------

def _local_default_schedule():
    t = timezone.localtime() + timedelta(days=1)
    return t.replace(hour=10, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def _aware(value: str):
    dt = datetime.fromisoformat(value)
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


CONTENT_ACTIONS = ("submit", "request_changes", "approve", "schedule", "unschedule", "publish", "retry", "reschedule", "edit_content", "delete_content", "adapt_content")


def _content_action(request, action: str) -> None:
    """Content Studio + Social calendar buttons → Content API."""
    cid = _int(request.POST.get("content_id"))
    base = f"/api/content/{cid}"
    if action == "reschedule":
        when = request.POST.get("scheduled_at")
        if not when:
            messages.error(request, "Pick a date and time.")
            return
        out = request.api.patch(base, {"scheduled_at": _aware(when).isoformat()})
        messages.success(request, f"Moved to {gm.when(out['scheduled_at'])}." if out["status"] == "scheduled" else f"Publish time set to {gm.when(out['scheduled_at'])}.")
    elif action == "edit_content":
        variants = [{"platform": p, "copy": request.POST.get(f"copy_{p}", "")} for p in request.POST.getlist("variant_platforms")]
        request.api.patch(base, {"topic": request.POST.get("topic", "").strip(), "master_copy": request.POST.get("master_copy", ""), "variants": variants,
                                 "image_url": request.POST.get("image_url", "").strip()})
        messages.success(request, "Changes saved.")
    elif action == "adapt_content":
        out = request.api.post(f"{base}/adapt")
        how = f"AI ({out['ai']['model']})" if out["ai"]["source"] == "ai" else "platform rules" + (f" — AI not used: {out['ai']['error']}" if out["ai"].get("error") else "")
        problems = [f"{gm.platform(v['platform'])}: {c['message']}" for v in out["variants"] for c in v["checks"] if c["level"] == "error"]
        messages.success(request, f"Rewrote each platform version from the master copy using {how}.")
        for p in problems:
            messages.warning(request, f"Fix before scheduling — {p}")
    elif action == "delete_content":
        request.api.delete(base)
        messages.success(request, "Deleted.")
    else:
        try:
            out = request.api.post(f"{base}/{action}")
        except ApiError as e:
            if e.status == 502:  # publish failed: the item is now tracked as Failed with the reason
                messages.error(request, f"Publishing failed: {e.detail}")
                return
            raise
        if action in ("publish", "retry"):
            if out.get("dispatch") == "queued":
                messages.success(request, "Queued — a Celery worker is publishing it now. Refresh in a moment.")
            elif out["status"] == "published":
                messages.success(request, "Published to " + ", ".join(gm.platform(v["platform"]) for v in out["variants"]) + ".")
            else:
                messages.warning(request, f"Not published yet: {out['last_error']} — retrying {gm.when(out['next_attempt_at'])}.")
        else:
            messages.success(request, {"submit": "Sent for approval.", "request_changes": "Sent back to draft.", "approve": "Approved and scheduled.",
                                       "schedule": "Scheduled.", "unschedule": "Unscheduled — back to Draft."}[action])


@login_required("content")
def content(request):
    cl = _clients(request)
    if not cl:
        return _no_clients(request, "AI Content Studio")
    brief_cid = _int(request.POST.get("client_id") or request.GET.get("client")) or cl[0]["id"]
    if request.me.get("client_id"):
        brief_cid = request.me["client_id"]
    ctx = {"clients": cl, "brief_cid": brief_cid, "types": CONTENT_TYPES, "when": _local_default_schedule(), "topic": "", "ctype": "post", "selected": ["gmb"]}

    if request.method == "POST":
        action = request.POST.get("action")
        if action in CONTENT_ACTIONS:
            _content_action(request, action)
            return _back(request)
        if action == "ai_draft":
            body = {"client_id": brief_cid, "topic": request.POST.get("topic", "").strip(), "content_type": request.POST.get("content_type", "post"),
                    "platforms": request.POST.getlist("platforms"), "notes": request.POST.get("notes", "").strip(),
                    "image_url": request.POST.get("image_url", "").strip()}
            if request.POST.get("scheduled_at"):
                body["scheduled_at"] = _aware(request.POST["scheduled_at"]).isoformat()
            try:
                d = request.api.post("/api/content/draft", body)
                how = f"AI ({d['ai']['model']})" if d["ai_source"] == "ai" else "the brand-voice template" + (f" — AI not used: {d['ai'].get('error')}" if d["ai"].get("error") else "")
                messages.success(request, f"Draft saved: “{d['topic']}”, written by {how}. Review it under Draft, then send for approval.")
                return redirect(f"{reverse('content')}?client={brief_cid}&board=draft#board")
            except ApiError as e:
                messages.error(request, e.detail)
        topic, ctype, selected = request.POST.get("topic", "").strip(), request.POST.get("content_type", "post"), request.POST.getlist("platforms")
        ctx.update(topic=topic, ctype=ctype, selected=selected, when=request.POST.get("scheduled_at") or ctx["when"])
        if action == "generate":
            try:
                ctx["draft"] = request.api.post("/api/content/generate", {"client_id": brief_cid, "topic": topic, "content_type": ctype, "platforms": selected,
                                                                    "notes": request.POST.get("notes", "").strip()})
            except ApiError as e:
                messages.error(request, e.detail)
        elif action in ("save_draft", "save_review", "save_schedule"):
            variants = [{"platform": p, "copy": request.POST.get(f"copy_{p}", ""), "format": request.POST.get(f"format_{p}", "1:1")} for p in request.POST.getlist("variant_platforms")]
            status = {"save_draft": "draft", "save_review": "in_review", "save_schedule": "scheduled"}[action]
            body = {"client_id": brief_cid, "topic": topic, "content_type": ctype, "master_copy": request.POST.get("master_copy", ""),
                    "ai_source": request.POST.get("ai_source", "") if request.POST.get("ai_source") in ("ai", "template") else "",
                    "image_url": request.POST.get("image_url", "").strip(),
                    "hashtags": json.loads(request.POST.get("hashtags") or "[]"), "creative_brief": request.POST.get("creative_brief", ""),
                    "variants": variants, "status": status, "scheduled_at": _aware(request.POST["scheduled_at"]).isoformat() if request.POST.get("scheduled_at") else None}
            try:
                request.api.post("/api/content", body)
                messages.success(request, {"draft": "Draft saved.", "in_review": "Sent for approval.", "scheduled": "Approved and scheduled."}[status])
                return redirect(f"{reverse('content')}?client={brief_cid}&board={'scheduled' if status == 'scheduled' else 'draft'}#board")
            except ApiError as e:
                messages.error(request, e.detail)
                ctx["draft"] = {"master_copy": body["master_copy"], "hashtags": body["hashtags"], "creative_brief": body["creative_brief"], "variants": variants, "source": "edited"}

    meta = request.api.get(f"/api/content/platforms/{brief_cid}")
    pipeline_cid = _client_filter(request)
    ctx.update(
        platforms=meta["platforms"], brand_voice=meta["brand_voice"], can_schedule=meta["can_schedule"],
        can_create=can(request, "content.create"), can_publish=can(request, "content.publish"),
        pipeline_cid=pipeline_cid, notes=request.POST.get("notes", ""), image_url=request.POST.get("image_url", ""),
    )
    group = request.GET.get("board", "scheduled")
    group = group if group in ("draft", "scheduled", "published", "failed", "all") else "scheduled"
    board = request.api._request("GET", "/api/content/board", params={"group": group, **({"client_id": pipeline_cid} if pipeline_cid else {})})
    ctx.update(board=board, items=board["items"], group=group,
               groups=[("draft", "Draft"), ("scheduled", "Scheduled"), ("published", "Published"), ("failed", "Failed"), ("all", "All")])
    if ctx.get("draft"):
        ctx["draft_hashtags_json"] = json.dumps(ctx["draft"].get("hashtags", []))
    return render(request, "portal/content.html", ctx)


# ---------- creative ----------

@login_required("creative")
def creative(request):
    cl = _clients(request)
    if not cl:
        return _no_clients(request, "Creative Studio")
    cid = _client_filter(request, cl[0]["id"])
    c = next(x for x in cl if x["id"] == cid)
    detail = request.api.get(f"/api/clients/{cid}")
    return render(request, "portal/creative.html", {
        "clients": cl, "cid": cid, "c": c, "headline": request.GET.get("headline", "Your headline here"), "cta": detail["brand_voice"].get("cta_style", "Contact us"),
        "sizes": [("Instagram feed", "4:5", 1080, 1350), ("Instagram / FB square", "1:1", 1080, 1080), ("Story / Reel", "9:16", 1080, 1920),
                  ("Google Business post", "4:3", 1200, 900), ("LinkedIn / link share", "1.91:1", 1200, 627), ("YouTube thumbnail", "16:9", 1280, 720)],
    })


# ---------- social ----------

def _meta_action(request, action: str):
    if action == "meta_connect":
        return ShareRedirect(request.api.post("/api/meta/connect")["auth_url"])
    if action == "meta_link":
        cid = _int(request.POST.get("client_id"))
        out = request.api.post(f"/api/clients/{cid}/meta/link", {"connection_id": _int(request.POST.get("connection_id")), "page_id": request.POST.get("page_id", ""),
                                                                  "instagram": "instagram" in request.POST})
        messages.success(request, "Linked " + " and ".join(gm.platform(p) for p in out["linked"]) + ". Posts for this client now publish for real."
                         + ("" if out["instagram_available"] else " (This Page has no Instagram professional account linked.)"))
    elif action == "meta_unlink":
        out = request.api.delete(f"/api/clients/{_int(request.POST.get('client_id'))}/meta")
        messages.success(request, f"Unlinked {', '.join(out['unlinked']) or 'nothing'}.")
    elif action == "meta_disconnect":
        out = request.api.delete(f"/api/meta/connections/{_int(request.POST.get('connection_id'))}")
        messages.success(request, f"Meta login removed and access revoked ({out['unlinked_accounts']} account(s) unlinked).")
    return HttpResponseRedirect(reverse("social") + "#meta")


def _calendar(request, cid):
    """Month (6 weeks) or week grid of posts by local day, from /api/content/calendar."""
    today = timezone.localdate()
    view = request.GET.get("view", "month")
    if view == "week":
        try:
            anchor = date.fromisoformat(request.GET.get("week", ""))
        except ValueError:
            anchor = today
        first = anchor - timedelta(days=anchor.weekday())
        days = [first + timedelta(days=i) for i in range(7)]
        title = f"{days[0]:%d %b} – {days[-1]:%d %b %Y}"
        nav = {"prev": {"week": (first - timedelta(days=7)).isoformat()}, "next": {"week": (first + timedelta(days=7)).isoformat()}}
    else:
        view = "month"
        try:
            month = date.fromisoformat(request.GET.get("month", "") + "-01")
        except ValueError:
            month = today.replace(day=1)
        days = [d for wk in calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month) for d in wk]
        title = f"{month:%B %Y}"
        nav = {"prev": {"month": (month - timedelta(days=1)).strftime("%Y-%m")}, "next": {"month": (month + timedelta(days=32)).strftime("%Y-%m")}}
        anchor = month
    start = timezone.make_aware(datetime.combine(days[0], datetime.min.time()))
    params = {"start": start.isoformat(), "days": len(days), **({"client_id": cid} if cid else {})}
    data = request.api._request("GET", "/api/content/calendar", params=params)
    by_day: dict[date, list] = {}
    for it in data["items"]:
        local = timezone.localtime(datetime.fromisoformat(it["at"]))
        by_day.setdefault(local.date(), []).append({**it, "time": local.strftime("%I:%M %p").lstrip("0")})
    cells = [{"date": d, "other": view == "month" and d.month != anchor.month, "today": d == today, "posts": by_day.get(d, [])} for d in days]
    return {"view": view, "cal_title": title, "weeks": [cells[i:i + 7] for i in range(0, len(cells), 7)], "nav": nav,
            "cal_count": len(data["items"]), "cal_groups": {g: sum(1 for x in data["items"] if x["group"] == g) for g in ("scheduled", "published", "failed", "draft")}}


@login_required("social")
def social(request):
    result = request.GET.get("meta", "")
    if result:
        kind, _, detail = result.partition(":")
        if kind == "connected":
            messages.success(request, f"Connected Meta as {detail}. Now link each client to its Facebook Page below.")
        else:
            messages.error(request, f"Meta connection failed: {detail}")
        return HttpResponseRedirect(reverse("social") + "#meta")
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "reconnect":
            request.api.post(f"/api/clients/{request.POST['client_id']}/social/{request.POST['platform']}/reconnect")
            messages.success(request, "Account reconnected.")
        elif action.startswith("meta_"):
            return _meta_action(request, action)
        elif action in CONTENT_ACTIONS:
            _content_action(request, action)
        return _back(request)
    cid = _client_filter(request)
    items = request.api.get("/api/content", client_id=cid)
    cl = _clients(request)
    accounts = []
    for c in cl if not cid else [x for x in cl if x["id"] == cid]:
        for s in request.api.get(f"/api/clients/{c['id']}")["social_accounts"]:
            accounts.append({**s, "client_id": c["id"], "client_name": c["company_name"]})
    meta = pages = None
    page_errors = []
    if can(request, "client.edit"):
        meta = request.api.get("/api/meta/status")
        if meta["configured"] and any(x["status"] == "active" for x in meta["connections"]):
            got = request.api.get("/api/meta/pages")
            pages, page_errors = got["pages"], got["errors"]
    return render(request, "portal/social.html", {
        **_calendar(request, cid), "cid": cid,
        "queue": [i for i in items if i["status"] not in ("published", "draft")], "accounts": accounts,
        "broken": [a for a in accounts if a["status"] != "connected"],
        "clients": None if request.me.get("client_id") else cl, "all_clients": cl, "can_publish": can(request, "content.publish"),
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "meta": meta, "pages": pages, "page_errors": page_errors,
        "live_clients": sorted({(a["client_id"], a["client_name"]) for a in accounts if a.get("is_live")}),
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
    if cl == []:
        return _no_clients(request, "Reports")
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
        action = request.POST.get("action", "workflow")
        if action == "workflow":
            request.api.patch("/api/settings", {"notify_on_negative_review": "notify" in request.POST, "require_client_approval": "client_approval" in request.POST})
            messages.success(request, "Settings saved.")
        elif action == "ai_test":
            r = request.api.post("/api/ai/test")["result"]
            if r["ok"]:
                messages.success(request, f"AI connection works: {r['model']} answered in {r['ms']} ms.")
            else:
                messages.error(request, f"AI connection failed ({r['code']}): {r['error']} {r.get('hint', '')}")
            return HttpResponseRedirect(reverse("settings") + "#ai")
        elif action == "create_user":
            body = {k: request.POST.get(k, "").strip() for k in ("name", "email", "password", "role")}
            body["client_id"] = _int(request.POST.get("client_id")) if body["role"] == "client" else None
            u = request.api.post("/api/users", body)
            messages.success(request, f"Created {u['email']} as {u['role_label']}. Share the password with them securely.")
        elif action == "update_user":
            patch = {"role": request.POST["role"], "status": request.POST["status"]}
            if request.POST["role"] == "client":
                patch["client_id"] = _int(request.POST.get("client_id"))
            if request.POST.get("password"):
                patch["password"] = request.POST["password"]
            u = request.api.patch(f"/api/users/{_int(request.POST.get('user_id'))}", patch)
            messages.success(request, f"Updated {u['email']}.")
        elif action == "update_role":
            name = request.POST["role"]
            request.api.patch(f"/api/roles/{name}", {"label": request.POST.get("label", "").strip() or None,
                                                     "sections": request.POST.getlist("sections"), "permissions": request.POST.getlist("permissions")})
            messages.success(request, f"Role “{name}” updated. Changes apply to signed-in users on their next page load.")
        return _back(request)
    s = request.api.get("/api/settings")
    health = request.api.get("/api/health")
    can_edit = can(request, "settings.edit")
    roles = request.api.get("/api/roles")
    matrix = [(sec, [sec in r["sections"] for r in roles["roles"]]) for sec in roles["sections"]]
    return render(request, "portal/settings.html", {
        "s": s, "health": health, "matrix": matrix, "can_edit": can_edit, "roles": roles,
        "users": request.api.get("/api/users"), "clients": _clients(request), "me_id": request.me["id"],
    })

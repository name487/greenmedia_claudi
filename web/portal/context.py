from .api import SESSION_ME

NAV = [
    ("dashboard", "dashboard", "Dashboard", "grid"),
    ("clients", "clients", "Clients", "users"),
    ("gmb", "gmb", "GMB Center", "pin"),
    ("reviews", "reviews", "AI Reviews", "star"),
    ("content", "content", "Content Studio", "pen"),
    ("creative", "creative", "Creative Studio", "image"),
    ("social", "social", "Social Hub", "calendar"),
    ("seo", "seo", "SEO Center", "search"),
    ("analytics", "analytics", "Analytics", "chart"),
    ("reports", "reports", "Reports", "file"),
    ("tasks", "tasks", "Team & Tasks", "check"),
    ("settings", "settings", "Settings", "gear"),
]


def nav(request):
    me = request.session.get(SESSION_ME)
    if not me:
        return {}
    current = getattr(request.resolver_match, "url_name", "")
    items = [
        {"url_name": url, "label": label, "icon": icon, "active": current == url or (url == "clients" and current == "client_detail")}
        for section, url, label, icon in NAV
        if section in me["sections"]
    ]
    return {"me": me, "nav_items": items, "perms": set(me["permissions"])}

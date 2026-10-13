from datetime import date, datetime

from django import template
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

TONE = {
    "active": "green", "onboarding": "blue", "paused": "gray",
    "new": "blue", "drafted": "purple", "approved": "amber", "published": "green", "rejected": "gray", "failed": "red",
    "draft": "gray", "in_review": "amber", "scheduled": "blue",
    "positive": "green", "neutral": "amber", "negative": "red",
    "todo": "gray", "in_progress": "blue", "review": "amber", "done": "green",
    "low": "gray", "medium": "amber", "high": "red",
    "connected": "green", "expired": "red", "disconnected": "red", "revoked": "red",
}

ICONS = {
    "grid": "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    "users": "M16 19v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9.5 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M21 19v-1a4 4 0 0 0-3-3.87M15 3.13a3.5 3.5 0 0 1 0 6.75",
    "pin": "M12 21s-7-6.1-7-11.5a7 7 0 0 1 14 0C19 14.9 12 21 12 21zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5",
    "star": "M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9z",
    "pen": "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
    "image": "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15.5 9.5a1.5 1.5 0 1 0 0-.01",
    "calendar": "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
    "search": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14M20 20l-4-4",
    "chart": "M4 20V10M10 20V4M16 20v-7M22 20H2",
    "file": "M6 3h8l5 5v13H6zM14 3v5h5M9 13h7M9 17h7",
    "check": "M4 12l5 5L20 6",
    "gear": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1",
    "menu": "M4 7h16M4 12h16M4 17h16",
    "sparkle": "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
    "back": "M15 18l-6-6 6-6",
}

PLATFORMS = {"gmb": "Google Business", "facebook": "Facebook", "instagram": "Instagram", "linkedin": "LinkedIn", "youtube": "YouTube", "x": "X"}


@register.simple_tag
def icon(name, size=20):
    return format_html(
        '<svg width="{}" height="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{}"/></svg>',
        size, size, ICONS.get(name, ""),
    )


@register.filter
def badge(status):
    s = str(status or "")
    return format_html('<span class="badge badge-{}">{}</span>', TONE.get(s, "gray"), s.replace("_", " "))


@register.filter
def stars(n):
    n = round(float(n or 0))
    return format_html('<span class="stars" aria-label="{} out of 5 stars">{}<span class="stars-off">{}</span></span>', n, "★" * n, "★" * (5 - n))


@register.filter
def platform(p):
    return PLATFORMS.get(p, p)


@register.filter
def compact(n):
    n = float(n or 0)
    for div, suf in ((1e7, "Cr"), (1e5, "L"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + suf
    return f"{int(n):,}"


@register.filter
def delta(pct):
    pct = int(pct or 0)
    if pct == 0:
        return mark_safe('<span class="delta flat">– 0%</span>')  # no change isn't growth
    return format_html('<span class="delta {}">{} {}%</span>', "up" if pct > 0 else "down", "▲" if pct > 0 else "▼", abs(pct))


@register.filter
def when(value, fmt="time"):
    """Parse API ISO strings into local datetimes for display."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime({"date": "%d %b", "long": "%d %b %Y", "time": "%d %b, %I:%M %p"}.get(fmt, "%d %b, %I:%M %p"))
    return value.strftime("%d %b %Y" if fmt == "long" else "%d %b")


@register.filter
def hours(value):
    """Compact duration from hours: 0 → "<1h", 30 → "30h", 50 → "2d"."""
    if value is None or value == "":
        return "—"
    h = float(value)
    if h < 1:
        return "<1h"
    return f"{round(h)}h" if h < 48 else f"{round(h / 24)}d"


@register.filter
def local_input(value):
    """ISO time from the API → value for <input type="datetime-local"> in the site's time zone."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.strftime("%Y-%m-%dT%H:%M")


@register.filter
def lines(values):
    """List → one item per line (for textareas); escaping still applies to the items."""
    return "\n".join(str(v) for v in values or [])


@register.filter
def split(value, sep=None):
    return str(value).split(sep)


@register.filter
def initials(name):
    parts = [p for p in str(name or "").replace(".", " ").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


@register.filter
def get(d, key):
    return d.get(key) if isinstance(d, dict) else None


@register.filter
def humanize(s):
    return str(s).replace("_", " ")


@register.simple_tag
def line_chart(rows, *specs, height=160):
    """rows: list of dicts; specs: "key|Label|color[|scale]" strings. Renders an inline SVG line chart."""
    if not rows:
        return mark_safe('<div class="empty">No data</div>')
    series = []
    for spec in specs:
        parts = spec.split("|")
        key, label, color = parts[0], parts[1], parts[2]
        scale = float(parts[3]) if len(parts) > 3 else 1
        series.append((label, color, [float(r.get(key, 0)) * scale for r in rows]))
    w = 600
    mx = max(1.0, *(v for _, _, vals in series for v in vals))
    n = len(rows)
    x = lambda i: 0 if n <= 1 else i / (n - 1) * w  # noqa: E731
    y = lambda v: height - 8 - v / mx * (height - 16)  # noqa: E731
    grid = "".join(f'<line x1="0" x2="{w}" y1="{height * f}" y2="{height * f}" class="gridline"/>' for f in (0.25, 0.5, 0.75))
    lines = "".join(
        f'<polyline fill="none" stroke="{escape(color)}" stroke-width="2" vector-effect="non-scaling-stroke" points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))}"/>'
        for _, color, vals in series
    )
    legend = "".join(f'<span><i style="background:{escape(c)}"></i> {escape(label)}</span>' for label, c, _ in series)
    rng = f'<span class="legend-range">{escape(rows[0].get("date", ""))} → {escape(rows[-1].get("date", ""))}</span>'
    return mark_safe(
        f'<figure class="chart"><svg viewBox="0 0 {w} {height}" preserveAspectRatio="none" role="img" aria-label="{escape(", ".join(s[0] for s in series))}">{grid}{lines}</svg>'
        f'<figcaption class="legend">{legend}{rng}</figcaption></figure>'
    )


@register.simple_tag
def bar_list(rows):
    """rows: list of (label, value)."""
    mx = max([v for _, v in rows] + [1])
    items = "".join(
        f'<li><span class="barlist-label">{escape(label)}</span><span class="barlist-track"><span style="width:{v / mx * 100:.1f}%"></span></span>'
        f'<span class="barlist-value">{v:,}</span></li>'
        for label, v in rows
    )
    return mark_safe(f'<ul class="barlist">{items}</ul>')


@register.simple_tag(takes_context=True)
def keep_params(context, *drop):
    """Hidden inputs for the current querystring minus `drop` (so auto-submitting filters keep other filters)."""
    request = context["request"]
    return mark_safe("".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">'
        for k, vals in request.GET.lists() if k not in drop and k not in ("report",) for v in vals
    ))


@register.simple_tag(takes_context=True)
def qs(context, **updates):
    """Current querystring with updates applied (None/'' removes a key)."""
    q = context["request"].GET.copy()
    for k, v in updates.items():
        if v in (None, ""):
            q.pop(k, None)
        else:
            q[k] = v
    return "?" + q.urlencode() if q else "?"

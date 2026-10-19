"""The monthly report as a PDF (app → Report → Download): A4 pages drawn with Pillow (no extra dependency), saved as one
multi-page PDF. Pages: Performance Summary, Growth Action Report, Performance Report, the agents' status, and what to do now."""

import io

from PIL import Image, ImageDraw

from .media import font

W, H = 1240, 1754  # A4 at 150 dpi
M = 70
NAVY, BLUE, GREEN, RED, AMBER = (14, 26, 58), (65, 105, 225), (46, 158, 91), (229, 72, 77), (224, 138, 30)
INK, MUTED, LINE, SOFT, TARGET = (20, 30, 40), (95, 107, 117), (225, 230, 236), (243, 246, 250), (200, 210, 245)


FALLBACKS = str.maketrans({"—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."})  # the built-in font lacks these


def _text(d: ImageDraw.ImageDraw, xy, s: str, size: int, fill=INK, bold: bool = False, anchor: str = "la") -> None:
    s = s.translate(FALLBACKS)
    d.text(xy, s, font=font(size), fill=fill, anchor=anchor, stroke_width=1 if bold else 0, stroke_fill=fill)


def _wrap(d: ImageDraw.ImageDraw, s: str, size: int, width: int) -> list[str]:
    s = s.translate(FALLBACKS)
    lines, cur = [], ""
    for w in s.split():
        t = f"{cur} {w}".strip()
        if d.textlength(t, font=font(size)) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def _page(title: str, business: str, month: str, n: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 120], fill=NAVY)
    _text(d, (M, 38), business, 34, "white", bold=True)
    _text(d, (M, 82), f"Monthly Report · {month}", 22, (200, 210, 230))
    d.rounded_rectangle([W - M - 210, 44, W - M, 84], 20, fill=(40, 56, 100))
    _text(d, (W - M - 105, 64), "Monthly Report", 20, "white", anchor="mm")
    _text(d, (M, 170), title, 40, NAVY, bold=True)
    d.rectangle([0, H - 70, W, H], fill=NAVY)
    _text(d, (M, H - 35), "Green Media AI Command Center", 18, (200, 210, 230), anchor="lm")
    _text(d, (W - M, H - 35), f"Page {n}", 18, (200, 210, 230), anchor="rm")
    return img, d


def _arrow(d, x: int, y: int, up: bool, colour) -> None:
    d.polygon([(x, y + 12), (x + 14, y + 12), (x + 7, y)] if up else [(x, y), (x + 14, y), (x + 7, y + 12)], fill=colour)


def _num(v) -> str:
    if v is None:
        return "–"
    return f"{v:,.1f}" if isinstance(v, float) else f"{v:,}"


def _tiles(d, summary: list[dict], top: int) -> int:
    cols, gap = 3, 22
    tw = (W - 2 * M - gap * (cols - 1)) // cols
    th = 150
    for i, s in enumerate(summary):
        x, y = M + (i % cols) * (tw + gap), top + (i // cols) * (th + gap)
        d.rounded_rectangle([x, y, x + tw, y + th], 18, fill=SOFT, outline=LINE, width=2)
        _text(d, (x + 24, y + 26), s["label"], 22, MUTED)
        _text(d, (x + 24, y + 62), _num(s["value"]) + s["unit"], 44, INK, bold=True)
        ch = s["change_pct"]
        colour = GREEN if ch > 0 else RED if ch < 0 else MUTED
        if ch:
            _arrow(d, x + 24, y + 116, ch > 0, colour)
        _text(d, (x + 46 if ch else x + 24, y + 112), f"{abs(ch):g}% vs last month" if ch else "same as last month", 19, colour)
    return top + ((len(summary) + cols - 1) // cols) * (th + gap)


def _bars(d, g: dict, top: int, height: int = 360) -> int:
    rows = g["periods"]["6m"]
    _text(d, (M, top), g["label"], 28, INK, bold=True)
    _text(d, (W - M, top + 4), f"Target {g['weekly_target']} a week · last 6 months", 18, MUTED, anchor="ra")
    lx = M + 160
    d.rectangle([lx, top + 44, lx + 18, top + 62], fill=TARGET)
    _text(d, (lx + 26, top + 42), "Target", 18, MUTED)
    d.rectangle([lx + 120, top + 44, lx + 138, top + 62], fill=BLUE)
    _text(d, (lx + 146, top + 42), "Achieved", 18, MUTED)
    y0, y1 = top + 90, top + height - 40
    vmax = max(1, *(max(r["target"], r["achieved"]) for r in rows))
    for k in range(5):
        y = y1 - (y1 - y0) * k / 4
        d.line([M + 50, y, W - M, y], fill=LINE, width=1)
        _text(d, (M + 40, y), str(round(vmax * k / 4)), 16, MUTED, anchor="rm")
    slot = (W - 2 * M - 60) / len(rows)
    for i, r in enumerate(rows):
        cx = M + 60 + slot * i + slot / 2
        for dx, v, col in ((-26, r["target"], TARGET), (4, r["achieved"], BLUE)):
            h = (y1 - y0) * v / vmax
            d.rectangle([cx + dx, y1 - h, cx + dx + 22, y1], fill=col)
        _text(d, (cx, y1 + 12), r["label"], 17, MUTED, anchor="ma")
        _text(d, (cx, y1 + 34), f"{r['achieved']}/{r['target']}", 16, GREEN if r["achieved"] >= r["target"] else MUTED, anchor="ma")
    return top + height + 30


def _line(d, t: dict, top: int, height: int = 380) -> int:
    _text(d, (M, top), t["label"], 28, INK, bold=True)
    _text(d, (W - M, top + 4), "Last 12 months", 18, MUTED, anchor="ra")
    pts = [(p["label"], p["value"]) for p in t["points"]]
    y0, y1 = top + 60, top + height - 150
    vals = [v for _, v in pts if v is not None]
    if not vals:
        d.rounded_rectangle([M, y0, W - M, y1], 16, fill=SOFT)
        _text(d, (W // 2, (y0 + y1) // 2 - 14), "No history yet", 24, INK, bold=True, anchor="mm")
        _text(d, (W // 2, (y0 + y1) // 2 + 20), "It's recorded every week; the chart fills in as the months go by.", 18, MUTED, anchor="mm")
    else:
        vmax, vmin = max(vals), min(0, min(vals))
        span = (vmax - vmin) or 1
        for k in range(5):
            y = y1 - (y1 - y0) * k / 4
            d.line([M + 60, y, W - M, y], fill=LINE, width=1)
            _text(d, (M + 50, y), f"{vmin + span * k / 4:,.0f}", 16, MUTED, anchor="rm")
        step = (W - 2 * M - 80) / max(1, len(pts) - 1)
        xy = [(M + 70 + step * i, y1 - (y1 - y0) * ((v - vmin) / span)) for i, (_, v) in enumerate(pts) if v is not None]
        d.line(xy, fill=BLUE, width=4, joint="curve")
        for x, y in xy:
            d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=BLUE)
        for i, (lab, _) in enumerate(pts):
            if i % 2 == 0 or i == len(pts) - 1:
                _text(d, (M + 70 + step * i, y1 + 12), lab, 16, MUTED, anchor="ma")
    by = y1 + 46
    lines = _wrap(d, t["insight"], 19, W - 2 * M - 80)
    d.rounded_rectangle([M, by, W - M, by + 30 + 26 * len(lines)], 16, fill=BLUE)
    for k, ln in enumerate(lines):
        _text(d, (M + 40, by + 16 + 26 * k), ln, 19, "white")
    d.ellipse([M + 14, by + 18, M + 28, by + 32], fill=(255, 214, 10))
    return by + 30 + 26 * len(lines) + 40


def _agent(d, x: int, y: int, w: int, h: int, name: str, sub: str, status: str, detail: str, colour, icon: str, ok: bool) -> None:
    d.rounded_rectangle([x, y, x + w, y + h], 20, fill="white", outline=LINE, width=2)
    _text(d, (x + 26, y + 26), name, 26, colour, bold=True)
    _text(d, (x + 26, y + 62), sub, 17, MUTED)
    d.rounded_rectangle([x + w - 70, y + 22, x + w - 26, y + 66], 10, fill=colour)
    _text(d, (x + w - 48, y + 44), icon, 22, "white", bold=True, anchor="mm")
    cx, cy = x + w // 2, y + h // 2 + 10
    d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=SOFT)
    if ok:  # drawn: the built-in font has no ✓
        d.line([(cx - 32, cy + 2), (cx - 8, cy + 26), (cx + 34, cy - 24)], fill=colour, width=12, joint="curve")
    else:
        _text(d, (cx, cy), "!", 64, colour, bold=True, anchor="mm")
    _text(d, (cx, y + h - 70), status, 26, INK, bold=True, anchor="mm")
    _text(d, (cx, y + h - 36), detail, 17, MUTED, anchor="mm")


def render(report: dict, pending: dict, actions: list[dict]) -> bytes:
    pages = draw(report, pending, actions)
    out = io.BytesIO()
    pages[0].save(out, "PDF", resolution=150, save_all=True, append_images=pages[1:],
                  title=f"{report['client']['company_name']} — {report['month_label']} report", author="Green Media AI Command Center")
    return out.getvalue()


def draw(report: dict, pending: dict, actions: list[dict]) -> list[Image.Image]:
    business, month = report["client"]["company_name"], report["month_label"]
    pages: list[Image.Image] = []

    img, d = _page(f"{month} Performance Summary", business, month, 1)
    _text(d, (M, 222), f"Compared with {report['previous_label']}", 22, MUTED)
    y = _tiles(d, report["summary"], 270) + 30
    _text(d, (M, y), "This month at a glance", 28, INK, bold=True)
    y += 50
    for g in report["growth"]:
        weeks = g["periods"]["last_month"]
        done, target = sum(w["achieved"] for w in weeks), sum(w["target"] for w in weeks)
        pct = min(1.0, done / target) if target else 0
        _text(d, (M, y), g["label"], 22)
        _text(d, (W - M, y), f"{done} of {target}", 22, GREEN if done >= target else INK, bold=True, anchor="ra")
        d.rounded_rectangle([M, y + 36, W - M, y + 50], 7, fill=LINE)
        if pct:
            d.rounded_rectangle([M, y + 36, M + (W - 2 * M) * pct, y + 50], 7, fill=GREEN if pct >= 1 else BLUE)
        y += 86
    pages.append(img)

    img, d = _page("Growth Action Report", business, month, 2)
    _text(d, (M, 222), "What was done each month against the target", 22, MUTED)
    y = 280
    for g in report["growth"]:
        y = _bars(d, g, y)
    pages.append(img)

    trends = report["trends"]
    for n, chunk in enumerate((trends[0:3], trends[3:6], trends[6:])):
        img, d = _page("Performance Report" + (" (continued)" if n else ""), business, month, len(pages) + 1)
        y = 240
        for t in chunk:
            y = _line(d, t, y)
        if n == 2:
            _text(d, (M, y + 10), "Your agents", 32, NAVY, bold=True)
            cw, ch, top = (W - 2 * M - 30) // 2, 420, y + 70
            rv, md, ps = pending["reviews_waiting"], pending["media_left"], pending["posts_waiting"]
            _agent(d, M, top, cw, ch, "Review Reply Agent", "Replies to every review to build trust",
                   "All Reviews Replied" if not rv else f"{rv} reviews waiting", "Get more reviews with your QR" if not rv else "Open Replies to approve",
                   RED, "R", not rv)
            _agent(d, M + cw + 30, top, cw, ch, "Media Agent", "Uploads your photos to Google on schedule",
                   "No Media Left" if not md else f"{md} photos scheduled", "Upload more to keep the profile fresh" if not md else "Going up one a day",
                   AMBER, "M", bool(md))
        pages.append(img)

    img, d = _page("What You Should Do Now?", business, month, len(pages) + 1)
    todo = [a for a in actions if not a["done"]][:6] or [{"title": "Keep it up", "detail": "Every growth action is done this month."}]
    y = 250
    for i, a in enumerate(todo, 1):
        d.rounded_rectangle([M, y, W - M, y + 110], 16, fill=SOFT, outline=LINE, width=2)
        d.ellipse([M + 24, y + 30, M + 74, y + 80], fill=NAVY)
        _text(d, (M + 49, y + 55), str(i), 24, "white", bold=True, anchor="mm")
        _text(d, (M + 100, y + 26), a["title"], 26, INK, bold=True)
        _text(d, (M + 100, y + 66), a.get("detail", ""), 19, MUTED)
        y += 130
    if pending["posts_waiting"]:
        _text(d, (M, y + 10), f"{pending['posts_waiting']} posts are waiting for your approval in the app.", 22, AMBER, bold=True)
        y += 60
    d.rounded_rectangle([M, y + 30, W - M, y + 150], 18, fill=(232, 240, 255))
    _text(d, (M + 30, y + 62), "Keep growing your business", 26, NAVY, bold=True)
    _text(d, (M + 30, y + 104), "See you next month with another report.", 20, MUTED)
    pages.append(img)
    return pages

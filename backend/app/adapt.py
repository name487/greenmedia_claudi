"""Per-platform content rules: adapt one master copy to each network, and check a version before it is scheduled.

check() errors block scheduling (the post would be rejected by the platform); warnings are shown next to the copy.
"""

import re

RULES = {
    #             max chars   hashtags  links clickable  needs image  note
    "facebook":  {"limit": 63206, "soft": 500, "hashtags": 3, "links": True, "image": False},
    "instagram": {"limit": 2200, "soft": 1000, "hashtags": 30, "links": False, "image": True},
    "gmb":       {"limit": 1500, "soft": 1500, "hashtags": 0, "links": True, "image": False},
    "linkedin":  {"limit": 3000, "soft": 1300, "hashtags": 5, "links": True, "image": False},
    "x":         {"limit": 280, "soft": 280, "hashtags": 2, "links": True, "image": False},
    "youtube":   {"limit": 5000, "soft": 5000, "hashtags": 15, "links": True, "image": False},
}
URL = re.compile(r"https?://\S+", re.I)
TAG = re.compile(r"(?<!\w)#\w+", re.U)


def hashtags_in(text: str) -> list[str]:
    return TAG.findall(text or "")


def check(platform: str, copy: str, image_url: str = "") -> list[dict]:
    """[{"level": "error"|"warning", "message"}]."""
    r = RULES.get(platform)
    if not r:
        return []
    out: list[dict] = []

    def add(level: str, msg: str):
        out.append({"level": level, "message": msg})

    text = (copy or "").strip()
    if not text:
        add("error", "Empty copy")
    if len(text) > r["limit"]:
        add("error", f"{len(text)} characters — the limit is {r['limit']}")
    elif len(text) > r["soft"] and r["soft"] < r["limit"]:
        add("warning", f"{len(text)} characters — only the first ~{r['soft']} show before “See more”")
    if r["image"] and not image_url:
        add("error", "Instagram needs an image — add an image URL to the post")
    if image_url and not image_url.lower().startswith("https://"):
        add("error", "The image must be a public https:// URL")
    tags = hashtags_in(text)
    if platform == "instagram" and len(tags) > 30:
        add("error", f"{len(tags)} hashtags — Instagram allows 30")
    elif r["hashtags"] == 0 and tags:
        add("warning", "Hashtags don't help on Google Business posts")
    elif len(tags) > r["hashtags"] > 0:
        add("warning", f"{len(tags)} hashtags — {r['hashtags']} or fewer works best here")
    if not r["links"] and URL.search(text):
        add("warning", "Links aren't clickable in Instagram captions — say “link in bio” instead")
    return out


def blocking(variants, image_url: str) -> list[str]:
    return [f"{v.platform}: {c['message']}" for v in variants for c in check(v.platform, v.copy, image_url) if c["level"] == "error"]


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:—- ")
    return cut + "…"


def adapt(platform: str, master: str, hashtags: list[str], website: str = "", cta: str = "") -> str:
    """Rule-based version of the master copy for one platform (used when the AI isn't available)."""
    body = TAG.sub("", master or "").strip()
    body = re.sub(r"[ \t]{2,}", " ", body)
    tags = [t if t.startswith("#") else f"#{t}" for t in (hashtags or [])] + [t for t in hashtags_in(master) if t not in (hashtags or [])]
    r = RULES[platform]
    if platform == "instagram":
        body = URL.sub("(link in bio)", body)
        tail = f"\n\n{cta} — link in bio." if cta else ""
        return _trim(body + tail + ("\n\n" + " ".join(tags[:30]) if tags else ""), r["limit"])
    if platform == "gmb":
        return _trim(body + (f" {cta}." if cta and cta.lower() not in body.lower() else ""), r["limit"])
    if platform == "x":
        tag_str = " ".join(tags[:2])
        return _trim(body, r["limit"] - len(tag_str) - 1) + (f" {tag_str}" if tag_str else "")
    link = f"\n\n{website}" if website and website not in body else ""
    if platform == "youtube":
        return _trim(f"{body}{link}" + ("\n\n" + " ".join(tags[:15]) if tags else ""), r["limit"])
    return _trim(body + link + ("\n\n" + " ".join(tags[: r["hashtags"]]) if tags else ""), r["limit"])

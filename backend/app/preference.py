"""Preference (mobile app → Settings): what the business tells us about itself — poster details (brand name, logo,
phone, address), its story (what makes it different, why visit, …), photos of the place and team, hashtags, and who it
wants to reach. Saved on the client; the words the AI should know are copied into the brand voice (ai._voice reads it),
and posters use the brand name, phone, address and logo."""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import media
from .models import Client, ProductItem

TEXT = {  # key: (label, max length)
    "brand_name": ("Brand Name", 80), "phone_on_poster": ("Phone on Poster", 20), "address_on_poster": ("Address on Poster", 160),
    "additional_info": ("Additional Info on Post", 160), "founder_name": ("Founder Name", 80),
    "different": ("How you are different than competition", 300), "why_visit": ("Why customer should visit you", 300),
    "low_standards": ("Low standards of industry", 300), "solutions_low_standards": ("Your solutions for low standards", 300),
    "solutions_malpractices": ("Your solutions for malpractices", 300), "common_mistakes": ("Common Mistakes by customers", 300),
    "guidelines": ("Guidelines to customer", 300), "landmark": ("Nearest Landmark / directions to reach", 200),
    "tagline": ("Business Tagline", 100), "description": ("Business Description", 750), "website": ("Website", 300),
    "tone": ("Tone of voice", 120),
}
CHOICES = {
    "founder_gender": ["Male", "Female", "Other", "Prefer not to say"],
    "target_gender": ["Unisex", "Men", "Women"],
    "target_age": ["All ages", "Under 18", "18-24", "25-34", "35-44", "45-54", "55+"],
    "region": ["Local (my city)", "My state", "All India", "International"],
    "model_ethnicity": ["Indian", "South Asian", "Any"],
    "audience": ["Everyone", "Families", "Students", "Young professionals", "Business owners", "Seniors", "Tourists"],
    "cta": ["Call now", "Book now", "Visit us", "Order online", "WhatsApp us", "Learn more"],
    "hashtag_mode": ["exact", "additional"],
}
TOGGLES = {"founder_in_promos": True}
PUBLISH = ["gmb", "facebook", "instagram"]
RELIGIONS = ["hindu", "muslim", "christian", "sikh", "jain", "buddhist"]
PHOTO_SLOTS = {"logo": "Brand Logo", "founder": "Founder Photo",
               **{f"interior_{i}": f"Interior Photo - {i} ({n})" for i, n in enumerate(["Entrance", "Seating / Counter", "Peak time rush photo",
                                                                                          "Additional", "Additional"], 1)},
               **{f"team_{i}": f"Team Photo - {i} ({n})" for i, n in enumerate(["With Owner", "Working", "At Entrance", "Additional",
                                                                                  "Additional"], 1)}}
MAX_HASHTAGS = 10
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def stored(c: Client) -> dict:
    return dict((c.brand_voice or {}).get("profile") or {})


def hashtags(raw: list[str], limit: int | None = MAX_HASHTAGS) -> list[str]:
    """'#Mumbai', 'best hotel', '#mumbai' → ['#Mumbai', '#besthotel'] (no duplicates, at most `limit`)."""
    out, seen = [], set()
    for h in raw:
        tag = "#" + re.sub(r"[^\w]", "", h.replace("#", ""), flags=re.U)
        if len(tag) > 1 and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag[:40])
    return out[:limit]


def view(db: Session, c: Client) -> dict:
    p = stored(c)
    contact = c.contacts[0] if c.contacts else None
    g = c.gmb
    bv = c.brand_voice or {}
    values = {
        **{k: p.get(k, "") for k in TEXT},
        "brand_name": p.get("brand_name") or c.company_name,
        "phone_on_poster": p.get("phone_on_poster") or (contact.phone if contact else ""),
        "address_on_poster": p.get("address_on_poster") or ((g.address if g else "") or c.city),
        "website": c.website, "tone": bv.get("tone", ""),
        **{k: p.get(k, "") for k in CHOICES},
        "hashtag_mode": p.get("hashtag_mode") or "additional", "target_gender": p.get("target_gender") or "Unisex",
        "founder_in_promos": p.get("founder_in_promos", True), "brand_color": p.get("brand_color", ""),
        "hashtags": p.get("hashtags", []),
        "publish": {k: (p.get("publish") or {}).get(k, True) for k in PUBLISH},
        "religious": {k: (p.get("religious") or {}).get(k, True) for k in RELIGIONS},
        "preferred_phrases": bv.get("preferred_phrases", []), "prohibited_claims": bv.get("prohibited_claims", []),
    }
    photos = {k: {"label": label, "url": media.url(p["photos"][k]) if (p.get("photos") or {}).get(k) else None} for k, label in PHOTO_SLOTS.items()}
    social = {a.platform: a for a in c.social_accounts}
    socials = [{"platform": "google", "connected": bool(g and g.status == "connected"),
                "account": (g.connection.email if g and g.connection else (g.google_email if g else "")) or (g.title if g else "")}]
    for plat in ("facebook", "instagram"):
        a = social.get(plat)
        socials.append({"platform": plat, "connected": bool(a and a.status == "connected"), "account": (a.handle if a else "") or ""})
    products = [{"id": i.id, "name": i.name, "image_url": media.url(i.image_path) if i.image_path else None}
                for i in db.scalars(select(ProductItem).where(ProductItem.client_id == c.id).order_by(ProductItem.id.desc()).limit(10))]
    return {"values": values, "photos": photos, "socials": socials, "products": products, "progress": progress(db, c, socials, photos),
            "labels": {k: v[0] for k, v in TEXT.items()}, "choices": CHOICES, "company_name": c.company_name, "maps_uri": g.maps_uri if g else ""}


def progress(db: Session, c: Client, socials: list[dict], photos: dict) -> dict:
    """The 6 things that make posts look like the business: shown as "Add Business Logo 2/6"."""
    has_product = (db.scalar(select(func.count()).select_from(ProductItem).where(ProductItem.client_id == c.id)) or 0) > 0
    steps = [
        ("google", "Connect Google", socials[0]["connected"]),
        ("social", "Connect Facebook or Instagram", any(s["connected"] for s in socials[1:])),
        ("product", "Add a Top Selling Item", has_product),
        ("logo", "Add Business Logo", bool(photos["logo"]["url"])),
        ("interior", "Add an Interior Photo", any(photos[f"interior_{i}"]["url"] for i in range(1, 6))),
        ("team", "Add a Team Photo", any(photos[f"team_{i}"]["url"] for i in range(1, 6))),
    ]
    nxt = next((s for s in steps if not s[2]), None)
    return {"done": sum(1 for s in steps if s[2]), "total": len(steps), "next": {"key": nxt[0], "label": nxt[1]} if nxt else None,
            "steps": [{"key": k, "label": label, "done": d} for k, label, d in steps]}


def update(c: Client, changes: dict) -> None:
    """Apply validated changes and copy what the AI should know into the brand voice."""
    p = stored(c)
    bv = dict(c.brand_voice or {})
    for k, v in changes.items():
        if k == "website":
            v = v.strip()
            c.website = ("https://" + v) if v and not re.match(r"^https?://", v) else v
        elif k == "tone":
            bv["tone"] = v.strip()
        elif k in ("preferred_phrases", "prohibited_claims"):
            bv[k] = [x.strip()[:120] for x in v if x.strip()][:10]
        elif k == "hashtags":
            p["hashtags"] = hashtags(v)
        elif k in ("publish", "religious"):
            p[k] = {**(p.get(k) or {}), **v}
        else:
            p[k] = v.strip() if isinstance(v, str) else v
    if p.get("cta"):
        bv["cta_style"] = p["cta"]
    # what the AI writes with (ai._voice): the business's own words
    bv["about"] = {k: p[k] for k in ("tagline", "description", "different", "why_visit", "solutions_low_standards", "solutions_malpractices",
                                      "guidelines", "landmark", "additional_info") if p.get(k)}
    bv["audience"] = {k: p[k] for k in ("target_gender", "target_age", "region", "audience") if p.get(k)}
    bv["profile"] = p
    c.brand_voice = bv


def set_photo(c: Client, slot: str, rel: str | None) -> None:
    p = stored(c)
    photos = dict(p.get("photos") or {})
    old = photos.get(slot)
    if rel:
        photos[slot] = rel
    else:
        photos.pop(slot, None)
    if old and old != rel:
        media.path_of(old).unlink(missing_ok=True)
    p["photos"] = photos
    c.brand_voice = {**(c.brand_voice or {}), "profile": p}


def poster_business(c: Client, base: dict) -> dict:
    """Posters and video end cards: the brand name, phone, address and logo the owner chose in Preference."""
    p = stored(c)
    out = dict(base)
    for key, field in (("name", "brand_name"), ("phone", "phone_on_poster"), ("address", "address_on_poster")):
        if p.get(field):
            out[key] = p[field]
    logo = (p.get("photos") or {}).get("logo")
    if logo:
        out["logo"] = logo
    if p.get("brand_color") and COLOR.match(p["brand_color"]):
        out["color"] = p["brand_color"]
    return out


def custom_hashtags(c: Client, generated: list[str]) -> list[str]:
    """"Use Exact Hashtag": only the owner's; "Use Additional Tags": theirs first, then the generated ones."""
    p = stored(c)
    own = p.get("hashtags") or []
    if not own:
        return generated
    if p.get("hashtag_mode") == "exact":
        return own
    return own + [h for h in generated if h.lower() not in {o.lower() for o in own}]


def publishes_on(c: Client, platform: str) -> bool:
    return (stored(c).get("publish") or {}).get(platform, True)


def with_hashtags(copy: str, tags: list[str]) -> str:
    """Replace a caption's hashtags with the chosen ones."""
    body = re.sub(r"(?<!\w)#\w+", "", copy, flags=re.U)
    body = re.sub(r"[ \t]{2,}", " ", body).rstrip()
    return f"{body}\n\n{' '.join(tags)}" if tags else body

"""Which of the business's search keywords a review reply uses — shown under each reply ("Keyword Used | Search
Volume") and given to the AI so replies mention what customers search for."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Keyword, SearchKeyword

# Words that don't make a keyword specific ("near me", "best", …) — a reply uses a keyword when it has its other words.
FILLER = {"near", "me", "in", "best", "top", "the", "a", "an", "for", "and", "of", "open", "now", "today", "good", "affordable", "cheap",
          "rated", "shop", "shops", "store", "stores", "services", "service", "price", "cost", "reviews", "contact", "number", "timings", "my"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9ऀ-ॿ]+", text.lower())


def for_clients(db: Session, client_ids: list[int]) -> dict[int, list[tuple[str, int]]]:
    """Each client's keywords with their monthly volume, best first: tracked keywords and Google search terms."""
    out: dict[int, dict[str, int]] = {cid: {} for cid in client_ids}
    for k in db.scalars(select(Keyword).where(Keyword.client_id.in_(client_ids))):
        out[k.client_id][k.keyword.lower()] = max(out[k.client_id].get(k.keyword.lower(), 0), k.volume or 0)
    for k in db.scalars(select(SearchKeyword).where(SearchKeyword.client_id.in_(client_ids))):
        out[k.client_id][k.keyword.lower()] = max(out[k.client_id].get(k.keyword.lower(), 0), k.impressions or 0)
    return {cid: sorted(kws.items(), key=lambda x: -x[1]) for cid, kws in out.items()}


def used(reply: str | None, keywords: list[tuple[str, int]], city: str = "", company: str = "", limit: int = 5) -> list[dict]:
    """Keywords whose specific words (not the filler, not the city) all appear in the reply. Searches for the business's
    own name don't count — every reply signed "— Team <name>" would match them."""
    if not reply:
        return []
    have = set(_words(reply))
    skip = FILLER | set(_words(city))
    brand = set(_words(company))
    out, seen = [], set()
    for kw, volume in keywords:  # highest volume first, so each set of words keeps its most-searched keyword
        core = [w for w in _words(kw) if w not in skip]
        if core and all(w in have for w in core) and not set(core) <= brand and frozenset(core) not in seen:
            seen.add(frozenset(core))
            out.append({"keyword": kw, "volume": volume, "words": core})
            if len(out) == limit:
                break
    return out

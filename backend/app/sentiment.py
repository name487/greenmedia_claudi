import re

NEG = ["rude", "terrible", "worst", "bad", "disappoint", "delay", "waited", "not happy", "poor", "dirty", "never", "refund", "dropped"]
POS = ["great", "wonderful", "best", "excellent", "amazing", "friendly", "recommend", "thank", "love", "clean", "polite", "अच्छी"]


def detect_sentiment(text: str, rating: int) -> str:
    """Rating-first heuristic with keyword nudges."""
    t = text.lower()
    score = (rating - 3) * 2 + sum(w in t for w in POS) - sum(w in t for w in NEG)
    if score >= 2:
        return "positive"
    if score <= -2:
        return "negative"
    return "neutral"


def detect_language(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    if re.search(r"[஀-௿]", text):
        return "ta"
    if re.search(r"[ఀ-౿]", text):
        return "te"
    return "en"

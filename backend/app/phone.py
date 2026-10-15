"""Phone numbers in E.164 (+919876543210). India by default: 10 digits starting 6-9."""

import re

COUNTRY_CODES = {"+91": (10, r"[6-9]\d{9}"), "+971": (9, r"5\d{8}"), "+1": (10, r"[2-9]\d{9}"), "+44": (10, r"7\d{9}")}


def normalize(phone: str, country_code: str = "+91") -> str:
    """Return +<cc><number> or raise ValueError with a message people can act on."""
    raw = re.sub(r"[\s\-().]", "", phone or "")
    cc = country_code if country_code.startswith("+") else f"+{country_code}"
    if raw.startswith("+"):
        cc = next((c for c in sorted(COUNTRY_CODES, key=len, reverse=True) if raw.startswith(c)), None)
        if cc is None:
            raise ValueError("Unsupported country code")
        raw = raw[len(cc):]
    elif cc == "+91" and len(raw) == 12 and raw.startswith("91"):
        raw = raw[2:]
    elif len(raw) == 11 and raw.startswith("0"):
        raw = raw[1:]
    if cc not in COUNTRY_CODES:
        raise ValueError("Unsupported country code")
    length, pattern = COUNTRY_CODES[cc]
    if not re.fullmatch(pattern, raw):
        raise ValueError(f"Enter a valid {length}-digit mobile number")
    return cc + raw


def masked(e164: str) -> str:
    return e164[:-6] + "••••" + e164[-2:] if len(e164) > 8 else e164

"""Access-token lifecycle for stored Google grants.

A *holder* is anything that stores a Google grant: an agency-level GoogleConnection or a client's own
GmbAccount. Both expose the same encrypted columns: refresh_token_enc, access_token_enc, token_expires_at.
Google access tokens live about an hour. We keep the current one (encrypted) in the database with its expiry
and swap it for a fresh one from the refresh token REFRESH_MARGIN before it runs out. Because the token is
stored in the database, the API workers and the background scheduler all share it, and it survives restarts.
"""

from datetime import datetime, timedelta, timezone

from . import api
from .crypto import decrypt, encrypt

REFRESH_MARGIN = timedelta(seconds=120)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt  # SQLite drops tzinfo


def needs_refresh(holder, now: datetime | None = None) -> bool:
    exp = _aware(holder.token_expires_at)
    return not holder.access_token_enc or exp is None or exp - (now or datetime.now(timezone.utc)) <= REFRESH_MARGIN


def store(holder, tokens: dict, now: datetime | None = None) -> None:
    """Save (encrypted) a token response from the code exchange or a refresh."""
    now = now or datetime.now(timezone.utc)
    if tokens.get("refresh_token"):  # sent on first consent, and when Google rotates it
        holder.refresh_token_enc = encrypt(tokens["refresh_token"])
    if tokens.get("access_token"):
        holder.access_token_enc = encrypt(tokens["access_token"])
        holder.token_expires_at = now + timedelta(seconds=int(tokens.get("expires_in", 3600)))


def access_token(holder, force_refresh: bool = False) -> str:
    """A valid access token for this holder, refreshing and persisting it when needed.
    Raises api.GoogleApiError (auth_failed=True when the grant is revoked or unreadable)."""
    if not holder.refresh_token_enc:
        raise api.GoogleApiError(401, "No Google sign-in stored — connect Google first.")
    if not force_refresh and not needs_refresh(holder):
        try:
            return decrypt(holder.access_token_enc)
        except ValueError:
            pass  # key rotated: fall through and get a new one
    try:
        refresh_token = decrypt(holder.refresh_token_enc)
    except ValueError as e:
        raise api.GoogleApiError(401, str(e)) from e
    tokens = api.refresh(refresh_token)
    store(holder, tokens)
    return tokens["access_token"]


def clear(holder) -> None:
    holder.access_token_enc, holder.token_expires_at = "", None


def expires_at_iso(holder) -> str | None:
    exp = _aware(holder.token_expires_at)
    return exp.isoformat() if exp else None

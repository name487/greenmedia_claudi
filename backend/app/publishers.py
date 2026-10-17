"""Outbound publishing to Google Business Profile and social networks.

Google Business Profile is live for any client linked to a real location (Settings → Google). Demo
clients, and the social networks (Meta Graph, LinkedIn, YouTube) until their OAuth apps are approved,
simulate success with a fake external id so the approval workflow and audit trail work end to end."""

import uuid

from .google import api as google_api
from .google import service as google
from .models import SAMPLE_REVIEW_PREFIX, Client


class PublishError(Exception):
    """transient=True: worth retrying later (rate limit, Google 5xx, network). False: needs a person (not connected, revoked, rejected)."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def _google_error(e: "google_api.GoogleApiError") -> PublishError:
    transient = e.status in (408, 429, 500, 502, 503, 504) and not e.approval_pending
    return PublishError(str(e), transient=transient)


def delete_review_reply(client: Client, external_review_id: str) -> None:
    """Remove the business's reply from a Google review (live clients); simulated for demo and sample reviews."""
    if external_review_id.startswith(SAMPLE_REVIEW_PREFIX) or not (client.gmb and client.gmb.is_live):
        return
    try:
        google.delete_reply(client, external_review_id)
    except google_api.GoogleApiError as e:
        raise _google_error(e) from e


def publish_review_reply(client: Client, external_review_id: str, reply: str) -> dict | None:
    """Live clients: Google Business Profile API `PUT …/reviews/{id}/reply`; returns Google's response
    ({"comment", "updateTime"}). Demo clients: simulated (None)."""
    if external_review_id.startswith(SAMPLE_REVIEW_PREFIX):
        return None  # sample review shown while Google API approval is pending: there is nothing on Google to reply to
    if not client.gmb or client.gmb.status != "connected":
        raise PublishError("Google Business Profile is not connected")
    if client.gmb.is_live:
        try:
            return google.publish_reply(client, external_review_id, reply)
        except google_api.GoogleApiError as e:
            raise _google_error(e) from e
    return None


def publish_post(client: Client, platform: str, copy: str, image_url: str = "", link: str = "") -> str:
    """Post one platform version. Live accounts go to the real API (Google Business Profile, Meta Graph for
    Facebook/Instagram); demo accounts are simulated with a fake id. Raises PublishError (transient or not)."""
    if platform == "gmb":
        if not client.gmb or client.gmb.status != "connected":
            raise PublishError("Google Business Profile is not connected")
        if client.gmb.is_live:
            try:
                return google.publish_post(client, copy)
            except google_api.GoogleApiError as e:
                raise _google_error(e) from e
    else:
        acct = next((a for a in client.social_accounts if a.platform == platform), None)
        if not acct:
            raise PublishError(f"No {platform} account connected")
        if acct.status != "connected":
            raise PublishError(f"{platform} token expired — reconnect the account")
        if acct.is_live and platform in ("facebook", "instagram"):
            return _publish_meta(acct, platform, copy, image_url, link)
    return f"{platform}_{uuid.uuid4().hex[:12]}"


def _publish_meta(acct, platform: str, copy: str, image_url: str, link: str) -> str:
    from .google.crypto import decrypt
    from .meta import api as meta

    if platform == "instagram" and not image_url:
        raise PublishError("Instagram posts need an image — add an image URL to this post")
    try:
        token = decrypt(acct.access_token_enc)
    except ValueError as e:
        acct.status, acct.last_error = "expired", str(e)
        raise PublishError(str(e)) from e
    try:
        if platform == "facebook":
            post_id = meta.publish_facebook(acct.external_id, token, copy, image_url=image_url, link=link)
        else:
            post_id = meta.publish_instagram(acct.external_id, token, copy, image_url)
    except meta.MetaApiError as e:
        acct.last_error = str(e)
        if e.auth_failed:
            acct.status = "expired"  # shows in Social Hub as "needs reconnection"
        raise PublishError(str(e), transient=e.transient) from e
    acct.last_error = ""
    return post_id

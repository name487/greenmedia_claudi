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


def publish_post(client: Client, platform: str, copy: str) -> str:
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
    return f"{platform}_{uuid.uuid4().hex[:12]}"

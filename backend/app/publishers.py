"""Outbound publishing to Google Business Profile and social networks.

These are the integration seams for the official APIs (GBP reviews/localPosts, Meta Graph, LinkedIn,
YouTube). Until OAuth apps are approved they simulate success and return a fake external id, so the
approval workflow, audit trail and failure handling can be exercised end to end."""

import uuid

from .models import Client


class PublishError(Exception):
    pass


def publish_review_reply(client: Client, external_review_id: str, reply: str) -> None:
    if not client.gmb or client.gmb.status != "connected":
        raise PublishError("Google Business Profile is not connected")
    # TODO: PUT https://mybusiness.googleapis.com/v4/{location}/reviews/{id}/reply


def publish_post(client: Client, platform: str, copy: str) -> str:
    if platform == "gmb":
        if not client.gmb or client.gmb.status != "connected":
            raise PublishError("Google Business Profile is not connected")
    else:
        acct = next((a for a in client.social_accounts if a.platform == platform), None)
        if not acct:
            raise PublishError(f"No {platform} account connected")
        if acct.status != "connected":
            raise PublishError(f"{platform} token expired — reconnect the account")
    return f"{platform}_{uuid.uuid4().hex[:12]}"

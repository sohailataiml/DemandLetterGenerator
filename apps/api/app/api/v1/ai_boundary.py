"""Diagnostics for the AI boundary: what is configured, and is it reachable.

Two distinct questions, deliberately kept apart:

*configured* is local — a URL, a key, a provider and a model are all present.
*reachable* costs a network call to the gateway's unauthenticated readiness
probe, so it happens only when asked for, never as part of this service's own
health check, and never by sending a prompt.

What this endpoint must never do is hand back the credential, or anything from
which it could be reconstructed. It reports booleans and names. A browser
calling it learns whether drafting will work, and nothing else — which is the
whole reason the frontend can be allowed to call it at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...config import get_settings
from ...gateway import GatewayError, build_client
from ...security.auth import CurrentUser, can_read

router = APIRouter(tags=["ops"])


@router.get("/ai-boundary")
def ai_boundary(
    probe: bool = Query(
        default=False,
        description="Also call the gateway's readiness probe. No prompt is sent.",
    ),
    user: CurrentUser = Depends(can_read),
) -> dict:
    settings = get_settings()
    boundary = {
        "secure_gateway": "secure_gateway",
        "anthropic": "direct_provider",
        "stub": "local",
    }.get(settings.llm_provider, "unknown")

    payload: dict[str, object] = {
        "llm_provider": settings.llm_provider,
        "ai_boundary": boundary,
        # The URL is not a secret; the key is, and is not represented here in
        # any form, not even as a length or a prefix.
        "secure_gateway_url": settings.secure_gateway_url,
        "secure_gateway_configured": settings.is_secure_gateway_configured,
        "upstream_provider": settings.secure_gateway_provider,
        "upstream_model": settings.secure_gateway_model,
        "bypasses_privacy_gateway": settings.llm_provider == "anthropic",
    }

    if not probe:
        return payload

    if not settings.is_secure_gateway_configured:
        payload["reachable"] = False
        payload["detail"] = "secure gateway is not configured"
        return payload

    try:
        with build_client() as client:
            readiness = client.readiness()
        payload["reachable"] = readiness.get("status") == "ready"
        payload["dependencies"] = readiness.get("dependencies", {})
    except GatewayError as exc:
        # An unreachable gateway is a fact about the gateway, not a failure of
        # this endpoint: it answers 200 with reachable=false so a dashboard can
        # distinguish "asked and it is down" from "could not ask".
        payload["reachable"] = False
        payload["detail"] = str(exc)
    return payload

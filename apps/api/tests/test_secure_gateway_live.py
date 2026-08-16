"""Opt-in contract test against the deployed Secure AI Gateway.

    SECURE_GATEWAY_API_KEY=sgw_live_... DLG_LIVE_GATEWAY=1 \\
        python -m pytest apps/api/tests/test_secure_gateway_live.py

Skipped unless **both** are set, so the ordinary suite stays offline and a
developer who merely has a key in their environment does not start making
network calls during `make gate`.

Everything sent here is synthetic — a made-up client, a made-up claim number, a
made-up provider — because the point is to check the wire contract, not to hand
real medical data to a test. Nothing in this file prints a credential.
"""

from __future__ import annotations

import json
import os

import pytest

from app.gateway import ChatMessage, SecureGatewayClient

LIVE = os.environ.get("DLG_LIVE_GATEWAY", "").strip().lower() in ("1", "true", "yes", "on")
API_KEY = os.environ.get("SECURE_GATEWAY_API_KEY", "")
BASE_URL = os.environ.get("SECURE_GATEWAY_URL", "https://sgw-api.onrender.com")
UPSTREAM_PROVIDER = os.environ.get("SECURE_GATEWAY_PROVIDER", "mock")
UPSTREAM_MODEL = os.environ.get("SECURE_GATEWAY_MODEL", "general-chat")

pytestmark = pytest.mark.skipif(
    not (LIVE and API_KEY),
    reason="live gateway test: set DLG_LIVE_GATEWAY=1 and SECURE_GATEWAY_API_KEY",
)

#: Synthetic through and through. No real client, claim, or record appears here.
SYNTHETIC_PROMPT = """\
Section to draft: imaging_summary — Diagnostic Imaging Findings

Structured case data (authoritative):
Client: Jane Example
Claim number: DEMO-123
Imaging provider: Example MRI Center

Verified facts available for this section:
- fact_1 (imaging_finding): MRI at Example MRI Center showed a disc extrusion at L5-S1 \
measuring 9 x 10 x 5 mm

Draft the section now. Return JSON with keys section, text, used_fact_ids, \
insufficient_evidence, missing.
"""


@pytest.fixture(scope="module")
def client() -> SecureGatewayClient:
    with SecureGatewayClient(
        base_url=BASE_URL, api_key=API_KEY, timeout_seconds=90
    ) as gateway:
        yield gateway


def test_the_deployment_is_ready(client):
    """Unauthenticated readiness. Sends no prompt and no PII."""
    readiness = client.readiness()

    assert readiness["status"] == "ready"
    assert isinstance(readiness.get("dependencies"), dict)


def test_the_configured_provider_and_model_are_allowed(client):
    catalogue = client.providers()

    aliases = {entry["alias"] for entry in catalogue["providers"]}
    assert UPSTREAM_PROVIDER in aliases, f"{UPSTREAM_PROVIDER!r} is not offered; have {aliases}"
    entry = next(e for e in catalogue["providers"] if e["alias"] == UPSTREAM_PROVIDER)
    assert entry["available"] is True
    if entry["models"]:
        assert UPSTREAM_MODEL in entry["models"], f"have {entry['models']}"


def test_a_synthetic_draft_round_trips_through_the_privacy_pipeline(client, capsys):
    reply = client.chat(
        provider=UPSTREAM_PROVIDER,
        model=UPSTREAM_MODEL,
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "You draft one section of a demand letter using only the supplied "
                    "verified facts. Return a single JSON object with keys section, text, "
                    "used_fact_ids, insufficient_evidence, missing."
                ),
            ),
            ChatMessage(role="user", content=SYNTHETIC_PROMPT),
        ],
        temperature=0.2,
        max_output_tokens=600,
    )

    # The deployed ChatResponse shape.
    assert reply.request_id and reply.session_id
    assert reply.provider == UPSTREAM_PROVIDER
    assert reply.content.strip()
    assert isinstance(reply.privacy, dict)
    for key in ("detected", "tokenized", "redacted", "pseudonymized", "blocked", "restored"):
        assert isinstance(reply.privacy.get(key, 0), int)

    # The credential is not in anything this test could print.
    printed = json.dumps(reply.metadata()) + capsys.readouterr().out
    assert API_KEY not in printed

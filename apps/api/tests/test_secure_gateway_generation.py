"""Generation through the gateway, over HTTP, with the demand as the witness.

The unit tests next door prove the client speaks the deployed contract. These
prove the thing an attorney actually cares about: when the boundary works the
letter is drafted and the privacy summary is recorded, and when it fails the
letter is exactly as they left it.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import get_settings
from app.domain.models import Demand
from app.gateway import SecureGatewayClient
from app.generation import composer
from app.generation.ai.secure_gateway import SecureGatewayProvider

from conftest import ATTORNEY, _post

API_KEY = "sgw_live_testonly_0000000000"
BASE_URL = "https://sgw-api.onrender.com"

PREVIEW = {
    "text": "Section to draft: imaging_summary\nClient: ⟦PERSON:••••⟧",
    "entity_summary": [{"entity_type": "PERSON", "count": 1, "action": "tokenize"}],
    "outbound_scan": "passed",
    "truncated": False,
}

PRIVACY = {
    "detected": 6,
    "tokenized": 2,
    "redacted": 1,
    "pseudonymized": 3,
    "blocked": 0,
    "allowed": 0,
    "restored": 2,
    "unknown_tokens": 0,
    "entity_types": {"PERSON": 3, "DATE_TIME": 2, "PHONE_NUMBER": 1},
}


def draft_for(section_key: str) -> str:
    return json.dumps(
        {
            "section": section_key,
            "text": f"Drafted {section_key} prose from the verified facts on file.",
            "used_fact_ids": [],
            "insufficient_evidence": False,
            "missing": "",
        }
    )


def chat_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    # Echo back a draft for whichever section this call was for.
    user = next(m["content"] for m in body["messages"] if m["role"] == "user")
    section = user.split("Section to draft:", 1)[1].split("—", 1)[0].strip()
    return httpx.Response(
        200,
        json={
            "request_id": f"req-{section}",
            "session_id": "11111111-2222-3333-4444-555555555555",
            "provider": body["provider"],
            "model": body["model"],
            "message": {"role": "assistant", "content": draft_for(section)},
            "privacy": PRIVACY,
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            "protected_preview": PREVIEW,
        },
    )


@pytest.fixture
def gateway_env(monkeypatch):
    monkeypatch.setenv("DLG_LLM_PROVIDER", "secure_gateway")
    monkeypatch.setenv("SECURE_GATEWAY_URL", BASE_URL)
    monkeypatch.setenv("SECURE_GATEWAY_API_KEY", API_KEY)
    monkeypatch.setenv("SECURE_GATEWAY_PROVIDER", "anthropic")
    monkeypatch.setenv("SECURE_GATEWAY_MODEL", "claude-opus-5")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def gateway_provider(handler) -> SecureGatewayProvider:
    return SecureGatewayProvider(
        client=SecureGatewayClient(
            base_url=BASE_URL,
            api_key=API_KEY,
            timeout_seconds=5,
            transport=httpx.MockTransport(handler),
        )
    )


def install(monkeypatch, handler) -> None:
    """Point the generation path at a mocked gateway, factory included."""
    provider = gateway_provider(handler)
    monkeypatch.setattr(composer, "get_provider", lambda: provider)


def error(status: int, code: str, headers: dict | None = None):
    return lambda request: httpx.Response(
        status,
        json={"error": {"code": code, "message": f"{code} from the gateway", "request_id": "req_x"}},
        headers=headers or {},
    )


# ------------------------------------------------------------- happy path


def test_a_demand_drafted_through_the_gateway_records_its_privacy_summary(
    client, seeded_case_with_facts, gateway_env, monkeypatch, db
):
    install(monkeypatch, chat_response)
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    generated = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    assert generated.status_code == 200, generated.text
    payload = generated.json()
    assert payload["provider_name"] == "secure_gateway"
    assert payload["model_name"] == "claude-opus-5"

    metadata = payload["generation_metadata"]
    assert metadata["ai_boundary"] == "secure_gateway"
    assert metadata["upstream_provider"] == "anthropic"
    assert metadata["calls"] >= 1
    # Counts are summed across the sections drafted in this run.
    assert metadata["privacy"]["detected"] == PRIVACY["detected"] * metadata["calls"]
    assert metadata["privacy"]["entity_types"]["PERSON"] == 3 * metadata["calls"]
    assert metadata["usage"]["total_tokens"] == 150 * metadata["calls"]
    assert len(metadata["gateway_request_ids"]) == metadata["calls"]

    # The prose in the letter is the restored assistant message.
    bodies = {section["key"]: section["body"] for section in payload["sections"]}
    assert "Drafted imaging_summary prose" in bodies["imaging_summary"]


def test_the_masked_preview_is_kept_per_section_for_review(
    client, seeded_case_with_facts, gateway_env, monkeypatch
):
    """An attorney reviewing AI prose can see what the provider was handed."""
    install(monkeypatch, chat_response)
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    payload = client.post(
        f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY
    ).json()

    sections = payload["generation_metadata"]["sections"]
    assert "imaging_summary" in sections
    record = sections["imaging_summary"]
    preview = record["protected_preview"]

    # The masked rendering, exactly as the gateway returned it.
    assert "⟦PERSON:" in preview["text"]
    assert preview["outbound_scan"] == "passed"
    assert record["gateway_request_id"]
    # And the restored prose is the section body, which is the other half.
    body = next(s["body"] for s in payload["sections"] if s["key"] == "imaging_summary")
    assert "Drafted imaging_summary prose" in body


def test_a_deployment_without_previews_still_generates(
    client, seeded_case_with_facts, gateway_env, monkeypatch
):
    """`protected_preview` is off by default on the gateway; that is not an error."""

    def _no_preview(request: httpx.Request) -> httpx.Response:
        response = chat_response(request)
        payload = json.loads(response.content)
        payload.pop("protected_preview", None)
        return httpx.Response(200, json=payload)

    install(monkeypatch, _no_preview)
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    payload = client.post(
        f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY
    ).json()

    metadata = payload["generation_metadata"]
    assert metadata["ai_boundary"] == "secure_gateway"
    assert metadata["sections"]["imaging_summary"]["protected_preview"] is None


def test_no_credential_or_prompt_reaches_the_audit_trail(
    client, seeded_case_with_facts, gateway_env, monkeypatch
):
    install(monkeypatch, chat_response)
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    events = client.get(f"/v1/cases/{case_id}/audit?limit=200", headers=ATTORNEY).json()
    generated = [e for e in events if e["event"] == "DEMAND_GENERATED"]
    serialized = json.dumps(events)

    assert generated, "generation was not audited"
    assert generated[0]["payload"]["ai_boundary"] == "secure_gateway"
    assert generated[0]["payload"]["privacy"]["tokenized"] >= 1
    assert API_KEY not in serialized
    assert "Section to draft" not in serialized, "a prompt was written to the audit trail"
    # The masked preview is a rendering of a prompt, and an append-only log is
    # the wrong place to accumulate those. It lives on the demand instead.
    assert "protected_preview" not in serialized
    assert "⟦PERSON:" not in serialized
    # The audit's own `sections` is the list of section keys it drafted, not the
    # per-section boundary records that carry previews.
    audited_sections = generated[0]["payload"]["sections"]
    assert isinstance(audited_sections, list)
    assert all(isinstance(key, str) for key in audited_sections)
    assert "imaging_summary" in audited_sections


def test_the_api_never_hands_the_gateway_key_to_a_client(
    client, seeded_case_with_facts, gateway_env
):
    """Everything a browser can read, checked against the credential."""
    case_id = seeded_case_with_facts["case_id"]
    paths = [
        "/health",
        "/v1/ai-boundary",
        "/v1/case-summaries",
        f"/v1/cases/{case_id}",
        f"/v1/cases/{case_id}/demands",
        f"/v1/cases/{case_id}/audit?limit=200",
        "/openapi.json",
    ]

    for path in paths:
        response = client.get(path, headers=ATTORNEY)
        assert response.status_code == 200, path
        assert API_KEY not in response.text, f"{path} leaked the gateway credential"
        assert "SECURE_GATEWAY_API_KEY" not in response.text, path


def test_the_boundary_endpoint_reports_configuration_without_the_secret(
    client, gateway_env
):
    payload = client.get("/v1/ai-boundary", headers=ATTORNEY).json()

    assert payload["ai_boundary"] == "secure_gateway"
    assert payload["secure_gateway_configured"] is True
    assert payload["bypasses_privacy_gateway"] is False
    assert payload["secure_gateway_url"] == BASE_URL
    assert API_KEY not in json.dumps(payload)
    # Probing is opt-in, so the plain call makes no network request.
    assert "reachable" not in payload


# ------------------------------------------------------------ failing closed


@pytest.mark.parametrize(
    ("status", "code", "expected_http", "expected_text"),
    [
        (429, "RATE_LIMIT_EXCEEDED", 429, "rate limiting"),
        (413, "REQUEST_TOO_LARGE", 413, "too large"),
        (422, "POLICY_VIOLATION", 422, "privacy policy declined"),
        (503, "VAULT_UNAVAILABLE", 502, "no changes were applied"),
        (504, "PROVIDER_TIMEOUT", 502, "no changes were applied"),
        (401, "AUTHENTICATION_FAILED", 502, "no changes were applied"),
    ],
)
def test_a_gateway_failure_preserves_the_existing_sections(
    client,
    seeded_case_with_facts,
    gateway_env,
    monkeypatch,
    status,
    code,
    expected_http,
    expected_text,
):
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    # First draft succeeds, so there is something to lose.
    install(monkeypatch, chat_response)
    first = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    assert first.status_code == 200
    before = {s["key"]: s["body"] for s in first.json()["sections"]}

    # Now the gateway starts failing.
    install(monkeypatch, error(status, code, headers={"Retry-After": "12"}))
    failed = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    assert failed.status_code == expected_http
    detail = failed.json()["detail"]
    assert expected_text in detail["message"]
    assert detail["gateway_error_code"] == code
    assert "No demand section was modified" in detail["message"] or "no " in detail["message"]

    after = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()
    assert {s["key"]: s["body"] for s in after["sections"]} == before
    assert after["status"] == "draft"


def test_a_rate_limited_generation_reports_retry_after(
    client, seeded_case_with_facts, gateway_env, monkeypatch
):
    install(monkeypatch, error(429, "RATE_LIMIT_EXCEEDED", headers={"Retry-After": "30"}))
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    response = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "30"


def test_an_oversized_context_fails_before_anything_is_sent(
    client, seeded_case_with_facts, gateway_env, monkeypatch
):
    """No silent truncation, no partial draft, and no trip past the boundary."""
    sent: list[httpx.Request] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return chat_response(request)

    install(monkeypatch, _handle)

    # Make the prompt enormous by inflating the context block the builder emits.
    from app.generation.ai import narratives

    monkeypatch.setattr(
        narratives, "build_context_block", lambda ctx: "x" * (300 * 1024)
    )

    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})
    response = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    assert response.status_code == 413
    assert "Reduce the section context" in response.json()["detail"]["message"]
    assert sent == [], "an oversized prompt must never leave the process"

    after = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()
    assert after["sections"] == []


def test_a_gateway_outage_does_not_fall_back_to_anthropic_over_http(
    client, seeded_case_with_facts, gateway_env, monkeypatch
):
    """The acceptance test: an outage is an outage, not a vendor call."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-be-used")
    get_settings.cache_clear()

    import app.generation.ai.provider as provider_module

    constructed: list[str] = []
    monkeypatch.setattr(
        provider_module,
        "AnthropicProvider",
        lambda *a, **k: constructed.append("anthropic"),
    )

    install(monkeypatch, error(502, "PROVIDER_UNAVAILABLE"))
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    response = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    assert response.status_code == 502
    assert constructed == []
    after = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()
    assert after["sections"] == []
    assert after["generation_metadata"] is None


def test_an_unapproved_demand_stays_unapproved_after_a_boundary_failure(
    client, seeded_case_with_facts, gateway_env, monkeypatch, db
):
    install(monkeypatch, error(503, "PRIVACY_DETECTOR_UNAVAILABLE"))
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    record = db.get(Demand, demand["id"])
    assert record.status == "draft"
    assert record.generated_at is None
    assert record.locked is False


# ------------------------------------------------- offline providers unchanged


def test_the_stub_path_records_a_local_boundary(client, seeded_case_with_facts):
    case_id = seeded_case_with_facts["case_id"]
    demand = _post(client, f"/v1/cases/{case_id}/demands", {})

    generated = client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)

    payload = generated.json()
    assert payload["provider_name"] == "stub"
    assert payload["generation_metadata"] == {"ai_boundary": "local"}

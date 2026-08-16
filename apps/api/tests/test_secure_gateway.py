"""The privacy boundary: contract, classification, and failing closed.

Every gateway HTTP call in this file is served by an in-process transport, so
the suite runs offline. What is asserted is the deployed contract as published
at https://sgw-api.onrender.com/openapi.json — request fields, response fields,
and the ``ErrorCode`` values — not a guess at it.

The load-bearing test is the last group: when the gateway is unavailable, no
draft is produced, no section is overwritten, and no direct vendor call is made.
A privacy boundary that silently steps aside under load is not a boundary.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import get_settings
from app.gateway import (
    MAX_REQUEST_BYTES,
    ChatMessage,
    GatewayAuthError,
    GatewayInvalidRequest,
    GatewayPolicyBlocked,
    GatewayRateLimited,
    GatewayRequestTooLarge,
    GatewayUnavailable,
    SecureGatewayClient,
)
from app.generation.ai import narratives
from app.generation.ai.prompts import SECTION_SPECS
from app.generation.ai.provider import (
    FactPayload,
    GroundedStubProvider,
    NarrativeRequest,
    ProviderError,
    get_provider,
)
from app.generation.ai.secure_gateway import SecureGatewayProvider

API_KEY = "sgw_live_testonly_0000000000"
BASE_URL = "https://sgw-api.onrender.com"

DRAFT_JSON = {
    "section": "imaging_summary",
    "text": "The MRI showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm.",
    "used_fact_ids": ["fact_1"],
    "insufficient_evidence": False,
    "missing": "",
}

#: A response shaped exactly like the deployed ``ChatResponse``.
CHAT_RESPONSE = {
    "request_id": "6f2b6a1e-2a54-4f38-9a0b-1f5f2f0d1c11",
    "session_id": "1b0c3e4d-55aa-4a1e-8f0f-99a1b2c3d4e5",
    "provider": "anthropic",
    "model": "claude-opus-5",
    "message": {"role": "assistant", "content": json.dumps(DRAFT_JSON)},
    "privacy": {
        "detected": 8,
        "tokenized": 3,
        "redacted": 1,
        "pseudonymized": 4,
        "blocked": 0,
        "allowed": 0,
        "restored": 3,
        "unknown_tokens": 0,
        "entity_types": {"PERSON": 4, "PHONE_NUMBER": 1},
    },
    "usage": {"input_tokens": 900, "output_tokens": 120, "total_tokens": 1020},
}


class Recorder:
    """Captures what was sent so the request contract can be asserted on."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []

    def transport(self, handler) -> httpx.MockTransport:
        def _handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.content:
                self.bodies.append(json.loads(request.content))
            return handler(request)

        return httpx.MockTransport(_handle)


def ok_handler(payload: dict = CHAT_RESPONSE):
    return lambda request: httpx.Response(200, json=payload)


def error_handler(status: int, code: str, message: str = "denied", headers: dict | None = None):
    def _handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"error": {"code": code, "message": message, "request_id": "req_1"}},
            headers=headers or {},
        )

    return _handle


def make_client(handler, recorder: Recorder | None = None) -> SecureGatewayClient:
    recorder = recorder or Recorder()
    return SecureGatewayClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout_seconds=5,
        transport=recorder.transport(handler),
    )


@pytest.fixture
def gateway_settings(monkeypatch):
    """Configure the gateway the way a deployment would, without a real key."""
    monkeypatch.setenv("DLG_LLM_PROVIDER", "secure_gateway")
    monkeypatch.setenv("SECURE_GATEWAY_URL", BASE_URL)
    monkeypatch.setenv("SECURE_GATEWAY_API_KEY", API_KEY)
    monkeypatch.setenv("SECURE_GATEWAY_PROVIDER", "anthropic")
    monkeypatch.setenv("SECURE_GATEWAY_MODEL", "claude-opus-5")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def narrative_request() -> NarrativeRequest:
    return NarrativeRequest(
        spec=SECTION_SPECS["imaging_summary"],
        context_block="Client: Jane Example\nClaim number: DEMO-123",
        facts=[
            FactPayload(
                id="fact_1",
                fact_type="imaging_finding",
                summary="MRI showed a disc extrusion at L5-S1 measuring 9 x 10 x 5 mm",
                value={"level": "L5-S1"},
                citations=["doc_1#p3"],
            )
        ],
    )


# --------------------------------------------------------------- the contract


def test_the_request_matches_the_deployed_chat_schema(gateway_settings):
    recorder = Recorder()
    client = make_client(ok_handler(), recorder)

    client.chat(
        provider="anthropic",
        model="claude-opus-5",
        messages=[ChatMessage("system", "rules"), ChatMessage("user", "draft")],
        temperature=0.2,
        max_output_tokens=2000,
    )

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/chat"

    body = recorder.bodies[0]
    # The deployed ChatRequest forbids unknown properties.
    assert set(body) <= {
        "session_id",
        "provider",
        "model",
        "messages",
        "temperature",
        "max_output_tokens",
    }
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-opus-5"
    assert body["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "draft"},
    ]
    # Absent optional fields are omitted rather than sent as null.
    assert "session_id" not in body


def test_the_bearer_credential_is_sent_and_nothing_else_carries_it(gateway_settings):
    recorder = Recorder()
    client = make_client(ok_handler(), recorder)

    client.chat(provider="anthropic", model="claude-opus-5", messages=[ChatMessage("user", "hi")])

    assert recorder.requests[0].headers["Authorization"] == f"Bearer {API_KEY}"
    # The Authorization header is the only place it travels. It is not in the
    # repr (which is what ends up in logs and tracebacks) and not on any public
    # attribute (which is what naive serializers walk).
    assert API_KEY not in repr(client)
    public = {name: getattr(client, name, None) for name in dir(client) if not name.startswith("_")}
    assert API_KEY not in [value for value in public.values() if isinstance(value, str)]


def test_no_tenant_or_policy_selector_is_sent(gateway_settings):
    """The gateway derives both from the principal; a caller cannot ask for less."""
    recorder = Recorder()
    client = make_client(ok_handler(), recorder)

    client.chat(provider="anthropic", model="claude-opus-5", messages=[ChatMessage("user", "hi")])

    body = recorder.bodies[0]
    assert "tenant" not in body and "tenant_id" not in body
    assert "policy" not in body and "policy_name" not in body


def test_the_restored_message_and_safe_metadata_are_captured(gateway_settings):
    client = make_client(ok_handler())

    reply = client.chat(
        provider="anthropic", model="claude-opus-5", messages=[ChatMessage("user", "hi")]
    )

    assert reply.content == json.dumps(DRAFT_JSON)
    assert reply.request_id == CHAT_RESPONSE["request_id"]
    assert reply.session_id == CHAT_RESPONSE["session_id"]
    assert reply.provider == "anthropic"
    assert reply.model == "claude-opus-5"
    assert reply.privacy["detected"] == 8
    assert reply.usage["total_tokens"] == 1020
    assert reply.latency_ms >= 0


def test_optional_response_fields_may_be_absent(gateway_settings):
    minimal = {
        "request_id": "r",
        "session_id": "s",
        "provider": "mock",
        "model": "general-chat",
        "message": {"role": "assistant", "content": json.dumps(DRAFT_JSON)},
        "privacy": {},
    }
    client = make_client(ok_handler(minimal))

    reply = client.chat(
        provider="mock", model="general-chat", messages=[ChatMessage("user", "hi")]
    )

    assert reply.usage is None
    assert reply.privacy == {}
    assert reply.metadata()["ai_boundary"] == "secure_gateway"


# ------------------------------------------------------------- error mapping


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "AUTHENTICATION_FAILED", GatewayAuthError),
        (401, "AUTHENTICATION_REQUIRED", GatewayAuthError),
        (403, "AUTHORIZATION_FAILED", GatewayAuthError),
        (403, "PROVIDER_NOT_ALLOWED", GatewayAuthError),
        (400, "INVALID_REQUEST", GatewayInvalidRequest),
        (409, "POLICY_NOT_FOUND", GatewayInvalidRequest),
        (422, "INVALID_REQUEST", GatewayInvalidRequest),
        (422, "POLICY_VIOLATION", GatewayPolicyBlocked),
        (422, "ENTITY_LIMIT_EXCEEDED", GatewayPolicyBlocked),
        (413, "REQUEST_TOO_LARGE", GatewayRequestTooLarge),
        (429, "RATE_LIMIT_EXCEEDED", GatewayRateLimited),
        (500, "INTERNAL_ERROR", GatewayUnavailable),
        (502, "PROVIDER_UNAVAILABLE", GatewayUnavailable),
        (503, "VAULT_UNAVAILABLE", GatewayUnavailable),
        (504, "PROVIDER_TIMEOUT", GatewayUnavailable),
    ],
)
def test_each_documented_error_code_maps_to_its_own_class(
    gateway_settings, status, code, expected
):
    client = make_client(error_handler(status, code))

    with pytest.raises(expected) as caught:
        client.chat(
            provider="anthropic", model="claude-opus-5", messages=[ChatMessage("user", "hi")]
        )

    assert caught.value.code == code
    assert caught.value.request_id == "req_1"


def test_a_policy_block_is_not_confused_with_a_malformed_request(gateway_settings):
    """Both are 422. One is a deliberate decision; the other is our bug."""
    blocked = make_client(error_handler(422, "POLICY_VIOLATION"))
    invalid = make_client(error_handler(422, "INVALID_REQUEST"))

    with pytest.raises(GatewayPolicyBlocked) as block:
        blocked.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])
    with pytest.raises(GatewayInvalidRequest):
        invalid.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert block.value.http_status == 422


def test_rate_limiting_is_distinct_and_carries_retry_after(gateway_settings):
    client = make_client(
        error_handler(429, "RATE_LIMIT_EXCEEDED", headers={"Retry-After": "30"})
    )

    with pytest.raises(GatewayRateLimited) as caught:
        client.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert caught.value.retry_after == 30
    assert caught.value.http_status == 429
    assert caught.value.retryable is False


def test_a_gateway_auth_failure_is_not_relayed_as_401_to_our_own_client(gateway_settings):
    """Our credential failed, not the attorney's session."""
    client = make_client(error_handler(401, "AUTHENTICATION_FAILED"))

    with pytest.raises(GatewayAuthError) as caught:
        client.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert caught.value.http_status == 502


def test_the_api_key_never_appears_in_an_error(gateway_settings):
    client = make_client(error_handler(401, "AUTHENTICATION_FAILED", message="bad key"))

    with pytest.raises(GatewayAuthError) as caught:
        client.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)
    assert API_KEY not in json.dumps(caught.value.as_audit_payload())


# ------------------------------------------------------------- request size


def test_an_oversized_request_fails_locally_before_it_is_sent(gateway_settings):
    recorder = Recorder()
    client = make_client(ok_handler(), recorder)
    huge = "x" * (MAX_REQUEST_BYTES + 1)

    with pytest.raises(GatewayRequestTooLarge) as caught:
        client.chat(provider="p", model="m", messages=[ChatMessage("user", huge)])

    # Nothing left the process: no round trip, no rate-limit budget spent.
    assert recorder.requests == []
    assert str(MAX_REQUEST_BYTES) in str(caught.value)


def test_a_request_within_the_limit_is_sent(gateway_settings):
    recorder = Recorder()
    client = make_client(ok_handler(), recorder)
    large_but_legal = "x" * (MAX_REQUEST_BYTES - 2048)

    client.chat(provider="p", model="m", messages=[ChatMessage("user", large_but_legal)])

    assert len(recorder.requests) == 1
    assert len(recorder.requests[0].content) <= MAX_REQUEST_BYTES


# ------------------------------------------------------------------ retries


def test_a_connection_failure_is_retried_once_and_then_surfaced(gateway_settings):
    attempts = {"count": 0}

    def _handle(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = SecureGatewayClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout_seconds=5,
        transport=httpx.MockTransport(_handle),
    )

    with pytest.raises(GatewayUnavailable):
        client.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert attempts["count"] == 2


def test_a_cold_start_that_recovers_on_the_second_attempt_succeeds(gateway_settings):
    """A Render free-tier wake-up looks exactly like this."""
    attempts = {"count": 0}

    def _handle(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("cold start", request=request)
        return httpx.Response(200, json=CHAT_RESPONSE)

    client = SecureGatewayClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout_seconds=5,
        transport=httpx.MockTransport(_handle),
    )

    reply = client.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert reply.request_id == CHAT_RESPONSE["request_id"]
    assert attempts["count"] == 2


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "AUTHENTICATION_FAILED"), (429, "RATE_LIMIT_EXCEEDED"), (413, "REQUEST_TOO_LARGE")],
)
def test_permanent_failures_are_never_retried(gateway_settings, status, code):
    attempts = {"count": 0}

    def _handle(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(status, json={"error": {"code": code, "message": "no"}})

    client = SecureGatewayClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout_seconds=5,
        transport=httpx.MockTransport(_handle),
    )

    with pytest.raises(Exception):
        client.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert attempts["count"] == 1


def test_a_timeout_is_not_retried_because_the_model_may_have_run(gateway_settings):
    """No idempotency mechanism is published, so a repeat could double-charge."""
    attempts = {"count": 0}

    def _handle(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ReadTimeout("too slow", request=request)

    client = SecureGatewayClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout_seconds=5,
        transport=httpx.MockTransport(_handle),
    )

    with pytest.raises(GatewayUnavailable):
        client.chat(provider="p", model="m", messages=[ChatMessage("user", "hi")])

    assert attempts["count"] == 1


# ------------------------------------------------------------ the provider


def test_the_factory_selects_the_gateway_provider(gateway_settings):
    provider = get_provider()

    assert isinstance(provider, SecureGatewayProvider)
    assert provider.name == "secure_gateway"
    assert provider.model == "claude-opus-5"


def test_the_factory_refuses_the_gateway_without_a_key(monkeypatch):
    monkeypatch.setenv("DLG_LLM_PROVIDER", "secure_gateway")
    monkeypatch.delenv("SECURE_GATEWAY_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ProviderError) as caught:
            get_provider()
        assert "SECURE_GATEWAY_API_KEY" in str(caught.value)
    finally:
        get_settings.cache_clear()


def test_the_provider_sends_the_grounding_prompt_and_returns_the_restored_draft(
    gateway_settings,
):
    recorder = Recorder()
    provider = SecureGatewayProvider(client=make_client(ok_handler(), recorder))

    result = provider.draft(narrative_request())

    body = recorder.bodies[0]
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user"]
    system, user = (m["content"] for m in body["messages"])
    # The grounding contract survives the move to the gateway.
    assert "Use ONLY the provided verified facts" in system
    assert "Do not state a total, a sum, or any arithmetic result" in system
    assert "fact_1" in user and "L5-S1" in user
    assert body["provider"] == "anthropic" and body["model"] == "claude-opus-5"

    assert result.provider == "secure_gateway"
    assert result.text == DRAFT_JSON["text"]
    assert result.used_fact_ids == ["fact_1"]
    assert result.gateway["gateway_request_id"] == CHAT_RESPONSE["request_id"]
    assert result.gateway["gateway_session_id"] == CHAT_RESPONSE["session_id"]
    assert result.gateway["upstream_provider"] == "anthropic"
    assert result.gateway["privacy"]["tokenized"] == 3


def test_the_provider_accepts_a_fenced_json_answer(gateway_settings):
    fenced = dict(CHAT_RESPONSE)
    fenced["message"] = {
        "role": "assistant",
        "content": f"```json\n{json.dumps(DRAFT_JSON)}\n```",
    }
    provider = SecureGatewayProvider(client=make_client(ok_handler(fenced)))

    assert provider.draft(narrative_request()).text == DRAFT_JSON["text"]


def test_a_model_answer_that_is_not_json_is_a_provider_error(gateway_settings):
    garbage = dict(CHAT_RESPONSE)
    garbage["message"] = {"role": "assistant", "content": "Sure! Here is the section..."}
    provider = SecureGatewayProvider(client=make_client(ok_handler(garbage)))

    with pytest.raises(ProviderError):
        provider.draft(narrative_request())


@pytest.mark.parametrize(
    ("status", "code", "expected_http"),
    [
        (429, "RATE_LIMIT_EXCEEDED", 429),
        (413, "REQUEST_TOO_LARGE", 413),
        (422, "POLICY_VIOLATION", 422),
        (401, "AUTHENTICATION_FAILED", 502),
        (503, "VAULT_UNAVAILABLE", 502),
    ],
)
def test_gateway_failures_reach_the_domain_as_classified_provider_errors(
    gateway_settings, status, code, expected_http
):
    provider = SecureGatewayProvider(client=make_client(error_handler(status, code)))

    with pytest.raises(ProviderError) as caught:
        provider.draft(narrative_request())

    assert caught.value.code == code
    assert caught.value.http_status == expected_http


def test_the_used_fact_filter_still_runs_on_gateway_drafts(gateway_settings, monkeypatch):
    """A model may only cite facts it was handed — gateway or not."""
    invented = dict(DRAFT_JSON, used_fact_ids=["fact_1", "fact_not_supplied"])
    payload = dict(CHAT_RESPONSE, message={"role": "assistant", "content": json.dumps(invented)})
    provider = SecureGatewayProvider(client=make_client(ok_handler(payload)))

    request = narrative_request()
    monkeypatch.setattr(narratives, "build_context_block", lambda ctx: request.context_block)
    monkeypatch.setattr(narratives, "facts_for_section", lambda ctx, spec: request.facts)

    result = narratives.generate_section(object(), request.spec, provider)

    assert result.used_fact_ids == ["fact_1"], "the uncited fact id was not dropped"
    # And the boundary metadata survives being rebuilt by the filter.
    assert result.gateway["gateway_request_id"] == CHAT_RESPONSE["request_id"]


# --------------------------------------------------------- failing closed


def test_a_gateway_outage_never_becomes_a_direct_vendor_call(gateway_settings, monkeypatch):
    """The one substitution that must never happen."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-be-used")
    get_settings.cache_clear()

    calls: list[str] = []

    class _Tripwire:
        def __init__(self, *args, **kwargs):
            calls.append("anthropic client constructed")

    import app.generation.ai.provider as provider_module

    monkeypatch.setattr(provider_module, "AnthropicProvider", _Tripwire)

    provider = SecureGatewayProvider(
        client=make_client(error_handler(503, "VAULT_UNAVAILABLE"))
    )

    with pytest.raises(ProviderError):
        provider.draft(narrative_request())

    assert calls == [], "the gateway failing must not reach for the vendor directly"


def test_the_stub_provider_still_drafts_offline(monkeypatch):
    monkeypatch.setenv("DLG_LLM_PROVIDER", "stub")
    get_settings.cache_clear()
    try:
        provider = get_provider()
        assert isinstance(provider, GroundedStubProvider)
        result = provider.draft(narrative_request())
        assert result.provider == "stub"
        assert "L5-S1" in result.text
        assert result.gateway == {}
    finally:
        get_settings.cache_clear()

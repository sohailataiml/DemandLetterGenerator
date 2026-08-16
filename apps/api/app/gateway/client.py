"""The one place this service talks to the Secure AI Gateway.

Everything that leaves the application trust boundary for an external model goes
through :meth:`SecureGatewayClient.chat`. Concentrating it here is what makes
the boundary auditable: there is a single URL, a single credential, a single
size check, and a single error taxonomy, and no drafting code anywhere else in
the repository imports ``httpx``.

Four rules this module exists to enforce:

* **The key never travels anywhere but the Authorization header.** It is not
  logged, not repr'd, not put in an exception, and not returned by any API of
  this service. :meth:`__repr__` is overridden for exactly that reason.
* **Oversized prompts fail here, locally.** The gateway caps ordinary bodies at
  256 KB; a request over that is rejected before it is sent, so the failure is a
  clear domain error rather than a wasted round trip against a per-principal
  rate limit.
* **Retries are conservative and never duplicate a generation.** Only failures
  where the gateway demonstrably did not process the request are retried, once.
  The gateway publishes no idempotency mechanism, so anything that might have
  reached the upstream model is surfaced rather than repeated.
* **The client is synchronous**, because the drafting path it serves is
  synchronous end to end (provider protocol, composer, job runner). Wrapping an
  async client in ``asyncio.run`` per section would create an event loop per
  paragraph and buy nothing.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import httpx

from ..config import get_settings
from .errors import (
    MAX_REQUEST_BYTES,
    GatewayError,
    GatewayRequestTooLarge,
    GatewayUnavailable,
    classify,
)

logger = logging.getLogger(__name__)

CHAT_PATH = "/v1/chat"
PROVIDERS_PATH = "/v1/providers"
READINESS_PATH = "/health/ready"

#: One extra attempt, and only for failures that never reached the model.
MAX_ATTEMPTS = 2

#: How much of the gateway's masked preview to keep. Enough to read the whole
#: prompt for a section, bounded so a demand row cannot grow without limit.
MAX_PREVIEW_CHARS = 6000

ROLES = ("system", "user", "assistant")


@dataclass(frozen=True)
class ChatMessage:
    """One turn of the request, matching the gateway's ``ChatMessage``."""

    role: str
    content: str

    def to_payload(self) -> dict[str, str]:
        if self.role not in ROLES:
            raise ValueError(f"unsupported message role {self.role!r}")
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatReply:
    """The gateway's restored answer, plus the safe metadata that came with it.

    ``content`` is the **restored** assistant message — the gateway has already
    put authorized values back. It is what the demand section is drafted from.

    ``privacy`` is counts only. The gateway documents its ``PrivacySummary`` as
    the sole privacy detail that leaves it: no detected value, no token, and no
    mapping is ever part of it, and this service stores it verbatim rather than
    deriving anything from it.
    """

    request_id: str
    session_id: str
    provider: str
    model: str
    content: str
    privacy: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] | None = None
    latency_ms: int = 0
    #: The gateway's masked rendering of what the provider actually received,
    #: when the deployment has ``PROTECTED_PREVIEW_ENABLED``. Its ``text`` holds
    #: no token identifiers — the gateway masks them to ``⟦TYPE:••••⟧`` before
    #: sending it, precisely so a browser can be shown this. Absent by default,
    #: and everything downstream treats it as optional.
    protected_preview: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        """Safe generation metadata for audit records and API responses."""
        return {
            "ai_boundary": "secure_gateway",
            "gateway_request_id": self.request_id,
            "gateway_session_id": self.session_id,
            "upstream_provider": self.provider,
            "upstream_model": self.model,
            "privacy": dict(self.privacy),
            "usage": dict(self.usage) if self.usage else None,
            "latency_ms": self.latency_ms,
            "protected_preview": self.preview(),
        }

    def preview(self) -> dict[str, Any] | None:
        """The masked preview, size-capped for storage. ``None`` when absent."""
        if not self.protected_preview:
            return None
        text = self.protected_preview.get("text")
        capped = isinstance(text, str) and len(text) > MAX_PREVIEW_CHARS
        return {
            "text": text[:MAX_PREVIEW_CHARS] if isinstance(text, str) else None,
            "entity_summary": list(self.protected_preview.get("entity_summary") or []),
            "outbound_scan": self.protected_preview.get("outbound_scan"),
            # Either the gateway truncated it, or this cap did.
            "truncated": bool(self.protected_preview.get("truncated")) or capped,
        }


class SecureGatewayClient:
    """Bearer-authenticated, size-checked client for the gateway's caller API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise GatewayError("secure gateway base URL is not configured")
        if not api_key:
            raise GatewayError("secure gateway API key is not configured")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        # Held privately and never surfaced. The name is deliberately not
        # `api_key`, so an attribute dump or a naive serializer does not find a
        # credential-shaped public field.
        self.__key = api_key
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=min(15.0, timeout_seconds)),
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic, but load-bearing
        return f"SecureGatewayClient(base_url={self.base_url!r}, api_key=<redacted>)"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SecureGatewayClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ chat

    def chat(
        self,
        *,
        provider: str,
        model: str,
        messages: Sequence[ChatMessage],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        session_id: str | None = None,
    ) -> ChatReply:
        """Run one chat request through the privacy pipeline.

        The gateway derives the tenant and the applicable policy from the
        authenticated principal, never from the body, so this sends no tenant or
        policy identifier: there is no request field through which this
        application — or its browser client — could ask for a weaker policy.
        """
        payload: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "messages": [message.to_payload() for message in messages],
        }
        # The request schema forbids unknown properties, so optional fields are
        # only present when they carry a value.
        if session_id is not None:
            payload["session_id"] = session_id
        if temperature is not None:
            payload["temperature"] = temperature
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens

        body = self._encode(payload)
        started = time.monotonic()
        response = self._send(CHAT_PATH, body)
        latency_ms = int((time.monotonic() - started) * 1000)
        return self._parse_chat(response, latency_ms=latency_ms)

    # ------------------------------------------------------- diagnostics only

    def readiness(self) -> dict[str, Any]:
        """The gateway's own readiness. Unauthenticated, and carries no content."""
        try:
            response = self._client.get(READINESS_PATH)
        except httpx.HTTPError as exc:
            raise GatewayUnavailable(f"secure gateway is unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise self._error_from(response)
        return response.json()

    def providers(self) -> dict[str, Any]:
        """Providers this deployment may call. For startup validation only."""
        response = self._send(PROVIDERS_PATH, body=None, method="GET")
        return response.json()

    # --------------------------------------------------------------- internals

    def _encode(self, payload: Mapping[str, Any]) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            # Local refusal, deliberately before the network call: the caller
            # gets a precise size rather than a 413 that cost a rate-limit slot.
            raise GatewayRequestTooLarge(
                f"request body is {len(body)} bytes; the secure AI gateway accepts at most "
                f"{MAX_REQUEST_BYTES} bytes",
                code="REQUEST_TOO_LARGE",
            )
        return body

    def _send(self, path: str, body: bytes | None, method: str = "POST") -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.__key}"}
        if body is not None:
            headers["Content-Type"] = "application/json"

        last: GatewayError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._client.request(
                    method, path, content=body, headers=headers
                )
            except httpx.TimeoutException as exc:
                # A read timeout may mean the model already ran. Without an
                # idempotency mechanism — the gateway publishes none — retrying
                # risks paying for a second generation, so this is surfaced.
                raise GatewayUnavailable(
                    f"secure gateway timed out after {self.timeout_seconds:g}s"
                ) from exc
            except httpx.HTTPError as exc:
                # Connection-level failure: nothing was processed. A Render cold
                # start looks exactly like this, and is worth one retry.
                last = GatewayUnavailable(
                    f"secure gateway is unreachable: {type(exc).__name__}"
                )
                if attempt >= MAX_ATTEMPTS:
                    raise last from exc
                continue

            if response.status_code < 400:
                return response

            error = self._error_from(response)
            if not error.retryable or attempt >= MAX_ATTEMPTS:
                raise error
            last = error

        raise last or GatewayUnavailable("secure gateway request failed")

    def _error_from(self, response: httpx.Response) -> GatewayError:
        code: str | None = None
        message = f"secure gateway returned HTTP {response.status_code}"
        request_id: str | None = None
        try:
            envelope = response.json()
        except ValueError:
            envelope = None
        if isinstance(envelope, dict):
            body = envelope.get("error")
            if isinstance(body, dict):
                code = body.get("code")
                message = body.get("message") or message
                request_id = body.get("request_id")

        error = classify(
            status=response.status_code,
            code=code,
            message=message,
            request_id=request_id,
            retry_after=_retry_after(response.headers),
        )
        logger.warning(
            "secure gateway error status=%s code=%s request_id=%s",
            response.status_code,
            code,
            request_id,
        )
        return error

    def _parse_chat(self, response: httpx.Response, *, latency_ms: int) -> ChatReply:
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayUnavailable("secure gateway returned a non-JSON response") from exc

        message = payload.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GatewayUnavailable("secure gateway returned an empty assistant message")

        usage = payload.get("usage")
        return ChatReply(
            request_id=str(payload.get("request_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            content=content,
            # Counts only, exactly as the gateway reported them. Optional
            # response fields stay optional: a deployment that omits `usage` or
            # returns a bare summary must not break drafting.
            privacy=dict(payload.get("privacy") or {}),
            usage=dict(usage) if isinstance(usage, dict) else None,
            latency_ms=latency_ms,
            protected_preview=(
                dict(preview) if isinstance(preview := payload.get("protected_preview"), dict) else None
            ),
        )


def _retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:  # pragma: no cover - a date form is valid but unused here
        return None


def build_client(transport: httpx.BaseTransport | None = None) -> SecureGatewayClient:
    """Construct the client from settings, failing loudly when unconfigured."""
    settings = get_settings()
    if not settings.secure_gateway_api_key:
        raise GatewayError(
            "SECURE_GATEWAY_API_KEY is not set; the secure AI gateway cannot be called"
        )
    return SecureGatewayClient(
        base_url=settings.secure_gateway_url,
        api_key=settings.secure_gateway_api_key,
        timeout_seconds=settings.secure_gateway_timeout_seconds,
        transport=transport,
    )

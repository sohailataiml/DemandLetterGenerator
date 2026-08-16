"""Narrative drafting through the Secure AI Gateway.

This is the preferred external drafting path. What changes compared with calling
a model vendor directly is *where the boundary is*, not what is sent: the same
verified facts and the same grounding contract go out, but they pass through the
gateway's privacy pipeline — detect, apply policy, tokenize or redact, outbound
scan, invoke the provider, restore authorized values — and the draft this
provider returns is the **restored** message.

What does not change is everything the rest of the system relies on. The gateway
is a privacy boundary, not a source of truth: the returned prose is still graded
against the verified fact store, still validated deterministically, and still
cannot be approved with a blocking issue outstanding.

Failure here is final. There is no fallback to a direct vendor call — that would
route the very content the gateway exists to protect around it — so a gateway
outage means the section is not drafted and the existing text is left alone.
"""

from __future__ import annotations

import json
import re

from ...config import get_settings
from ...gateway import ChatMessage, GatewayError, SecureGatewayClient, build_client
from .prompts import (
    JSON_OUTPUT_INSTRUCTION,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from .provider import NarrativeRequest, NarrativeResult, ProviderError

#: Low but non-zero: the draft should be steady across regenerations without
#: reading like a template.
TEMPERATURE = 0.2

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class SecureGatewayProvider:
    """Drafts sections by calling ``POST /v1/chat`` on the Secure AI Gateway."""

    name = "secure_gateway"

    def __init__(self, client: SecureGatewayClient | None = None) -> None:
        settings = get_settings()
        self.upstream_provider = settings.secure_gateway_provider
        # ``model`` is the name the rest of the application already records on a
        # demand, so it is the upstream model the gateway was asked for.
        self.model = settings.secure_gateway_model
        self._max_output_tokens = settings.secure_gateway_max_output_tokens
        self._owns_client = client is None
        try:
            self._client = client or build_client()
        except GatewayError as exc:
            raise ProviderError(str(exc)) from exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def draft(self, request: NarrativeRequest) -> NarrativeResult:
        messages = [
            # The system turn carries the grounding contract; the JSON contract
            # is appended here because ``/v1/chat`` has no structured-output
            # field — the deployed schema accepts provider, model, messages,
            # temperature and max_output_tokens, and nothing else.
            ChatMessage(role="system", content=f"{SYSTEM_PROMPT}\n{JSON_OUTPUT_INSTRUCTION}"),
            ChatMessage(
                role="user",
                content=build_user_prompt(
                    spec=request.spec,
                    context_block=request.context_block,
                    facts_block=request.facts_block(),
                ),
            ),
        ]

        try:
            reply = self._client.chat(
                provider=self.upstream_provider,
                model=self.model,
                messages=messages,
                temperature=TEMPERATURE,
                max_output_tokens=self._max_output_tokens,
            )
        except GatewayError as exc:
            # Classification is preserved so the API can answer 429 as 429 and
            # a policy block as a policy block, without the domain layer ever
            # seeing an HTTP status.
            raise ProviderError(
                str(exc),
                code=exc.code,
                retry_after=exc.retry_after,
                request_id=exc.request_id,
                http_status=exc.http_status,
            ) from exc

        payload = _parse(reply.content)
        return NarrativeResult(
            section_key=payload.get("section") or request.spec.key,
            # The restored assistant message is what the letter is drafted from.
            text=(payload.get("text") or "").strip(),
            used_fact_ids=list(payload.get("used_fact_ids") or []),
            insufficient_evidence=bool(payload.get("insufficient_evidence")),
            provider=self.name,
            model=self.model,
            prompt_version=PROMPT_VERSION,
            missing=payload.get("missing") or None,
            gateway=reply.metadata(),
        )


def _parse(content: str) -> dict:
    """Read the model's JSON answer, tolerating a code fence around it."""
    cleaned = _FENCE.sub("", content.strip()).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"secure gateway returned non-JSON draft output: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProviderError("secure gateway returned a draft that is not a JSON object")
    return payload

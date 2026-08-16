"""Providers that draft a bounded revision to one section.

The contract is narrower than drafting: the model is given the current text,
the attorney's instruction, and an explicit list of what it may not change. It
returns replacement text and nothing else — no fact ids it invented, no new
sections, no commentary.

``RhetoricalStubProvider`` is the offline default. It applies a small set of
deterministic rewrites that sharpen tone without touching any literal, which is
exactly the behaviour the constraint checker is there to enforce. It cannot
satisfy every instruction, and when it cannot it says so instead of inventing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from ..config import get_settings

REVISION_PROMPT_VERSION = "revision_v1"

SYSTEM_PROMPT = """\
You revise one section of an attorney's demand letter.

You are given the current text of the section, an instruction from the
attorney, and a list of constraints. You return replacement text.

HARD RULES

- Do not introduce, remove or change any dollar amount. Monetary figures are
  computed by the system from verified records; a rewrite may restate them
  exactly or not at all.
- Do not introduce, remove or change any date.
- Do not name any person, provider, or organisation that the current text does
  not already name.
- Do not assert anything the current text does not already assert. You may
  change how forcefully something is said. You may not change what is said.
- Do not add caveats, headings, or commentary about your own work.

Rhetorical strength comes from sentence structure and word choice, not from
new claims. "The driver failed to stop" is stronger than "a collision
occurred"; both assert the same fact.

Return replacement text for the section only.
"""

REVISION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "changed", "explanation"],
    "properties": {
        "text": {"type": "string", "description": "Replacement text for the section."},
        "changed": {
            "type": "boolean",
            "description": "False if the instruction cannot be met without breaking a rule.",
        },
        "explanation": {
            "type": "string",
            "description": "One sentence on what was changed, or why it could not be.",
        },
    },
}


@dataclass(frozen=True)
class RevisionRequest:
    section_key: str
    section_title: str
    current_text: str
    instruction: str
    constraint_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class RevisionDraft:
    text: str
    changed: bool
    explanation: str
    provider: str
    model: str | None = None
    prompt_version: str = REVISION_PROMPT_VERSION


class RevisionProvider(Protocol):
    name: str
    model: str | None

    def revise(self, request: RevisionRequest) -> RevisionDraft: ...


class RevisionError(RuntimeError):
    """The provider could not produce a usable revision.

    Carries the same optional boundary classification as ``ProviderError`` so a
    rate limit or a policy block reaches the reviewer as itself. See
    ``app/generation/ai/provider.py`` for why ``http_status`` is this service's
    answer rather than the upstream's.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retry_after: float | None = None,
        request_id: str | None = None,
        http_status: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.request_id = request_id
        self.http_status = http_status


# ------------------------------------------------------------------- stub provider

#: Hedges that weaken a sentence without adding information.
_HEDGE_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bit appears that\b\s*", re.I), ""),
    (re.compile(r"\bit seems that\b\s*", re.I), ""),
    (re.compile(r"\bapparently\b\s*", re.I), ""),
    (re.compile(r"\bmay have\b", re.I), "did"),
    (re.compile(r"\bseems to have\b", re.I), "did"),
    (re.compile(r"\bsomewhat\b\s*", re.I), ""),
    (re.compile(r"\ba collision occurred\b", re.I), "the collision occurred"),
    (re.compile(r"\bwas involved in\b", re.I), "caused"),
)

_SOFTENING_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bmust\b", re.I), "should"),
    (re.compile(r"\bwill not\b", re.I), "is unlikely to"),
)

_FORCEFUL = ("forceful", "stronger", "strengthen", "assertive", "firmer", "sharper")
_SOFTER = ("soften", "gentler", "less aggressive", "more measured", "tone down")
_CONCISE = ("concise", "shorter", "tighten", "trim", "brief")


class RhetoricalStubProvider:
    """Deterministic rewrites that change emphasis and never change literals."""

    name = "stub"
    model = None

    def revise(self, request: RevisionRequest) -> RevisionDraft:
        instruction = request.instruction.lower()
        text = request.current_text

        if any(word in instruction for word in _FORCEFUL):
            revised = self._apply(text, _HEDGE_REWRITES)
            note = "Removed hedging language; the assertions are unchanged."
        elif any(word in instruction for word in _SOFTER):
            revised = self._apply(text, _SOFTENING_REWRITES)
            note = "Softened modal verbs; the assertions are unchanged."
        elif any(word in instruction for word in _CONCISE):
            revised = self._condense(text)
            note = "Removed filler; no sentence was dropped."
        else:
            return RevisionDraft(
                text=text,
                changed=False,
                explanation=(
                    "This offline drafter only adjusts emphasis (stronger, softer, more "
                    "concise). Configure DLG_LLM_PROVIDER=anthropic for open-ended edits."
                ),
                provider=self.name,
            )

        revised = re.sub(r"[ \t]{2,}", " ", revised).strip()
        return RevisionDraft(
            text=revised,
            changed=revised != text.strip(),
            explanation=note,
            provider=self.name,
        )

    @staticmethod
    def _apply(text: str, rules) -> str:
        result = text
        for pattern, replacement in rules:
            result = pattern.sub(replacement, result)
        # Re-capitalize any sentence a removal left starting lowercase.
        return re.sub(
            r"(^|(?<=[.!?]\s))([a-z])", lambda m: m.group(1) + m.group(2).upper(), result
        )

    @staticmethod
    def _condense(text: str) -> str:
        filler = re.compile(
            r"\b(?:in order to|at this point in time|it should be noted that|"
            r"for all intents and purposes)\b\s*",
            re.I,
        )
        return filler.sub("", text)


# -------------------------------------------------------------- anthropic provider


class AnthropicRevisionProvider:
    """Claude, with the constraint list stated in the prompt and enforced in code."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.anthropic_model
        self._effort = settings.anthropic_effort
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RevisionError(
                "the 'anthropic' package is not installed; "
                "run `pip install anthropic` or set DLG_LLM_PROVIDER=stub"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

    def revise(self, request: RevisionRequest) -> RevisionDraft:  # pragma: no cover - network
        constraints = "\n".join(f"- {line}" for line in request.constraint_lines) or "- none"
        prompt = f"""\
Section: {request.section_title} ({request.section_key})

Attorney instruction:
{request.instruction}

Constraints you must not break:
{constraints}

Current text of the section:
---
{request.current_text}
---

Return replacement text for this section.
"""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": REVISION_SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RevisionError("model declined to revise this section")
        if response.stop_reason == "max_tokens":
            raise RevisionError("revision was truncated at max_tokens")

        block = next((b for b in response.content if b.type == "text"), None)
        if block is None:
            raise RevisionError("model returned no text block")
        try:
            payload = json.loads(block.text)
        except json.JSONDecodeError as exc:
            raise RevisionError(f"model returned non-JSON output: {exc}") from exc

        return RevisionDraft(
            text=(payload.get("text") or "").strip(),
            changed=bool(payload.get("changed")),
            explanation=(payload.get("explanation") or "").strip(),
            provider=self.name,
            model=self.model,
        )


# --------------------------------------------------- secure gateway provider


class SecureGatewayRevisionProvider:
    """Revisions through the Secure AI Gateway's privacy pipeline.

    A revision prompt carries the section's *current text*, which is the part of
    a demand most likely to name a claimant, a provider and a date — so it is
    exactly the payload that should cross a privacy boundary rather than go
    straight to a vendor. The replacement text used is the restored response,
    and the constraint checker still runs over it afterwards: the gateway
    protects the data, it does not vouch for the edit.
    """

    name = "secure_gateway"

    def __init__(self, client=None) -> None:
        from ..gateway import GatewayError, build_client

        settings = get_settings()
        self.upstream_provider = settings.secure_gateway_provider
        self.model = settings.secure_gateway_model
        self._max_output_tokens = settings.secure_gateway_max_output_tokens
        try:
            self._client = client or build_client()
        except GatewayError as exc:
            raise RevisionError(str(exc)) from exc

    def revise(self, request: RevisionRequest) -> RevisionDraft:
        from ..gateway import ChatMessage, GatewayError

        constraints = "\n".join(f"- {line}" for line in request.constraint_lines) or "- none"
        prompt = f"""\
Section: {request.section_title} ({request.section_key})

Attorney instruction:
{request.instruction}

Constraints you must not break:
{constraints}

Current text of the section:
---
{request.current_text}
---

Return replacement text for this section.
"""
        try:
            reply = self._client.chat(
                provider=self.upstream_provider,
                model=self.model,
                messages=[
                    ChatMessage(
                        role="system", content=f"{SYSTEM_PROMPT}\n{JSON_OUTPUT_INSTRUCTION}"
                    ),
                    ChatMessage(role="user", content=prompt),
                ],
                temperature=0.2,
                max_output_tokens=self._max_output_tokens,
            )
        except GatewayError as exc:
            raise RevisionError(
                str(exc),
                code=exc.code,
                retry_after=exc.retry_after,
                request_id=exc.request_id,
                http_status=exc.http_status,
            ) from exc

        payload = _parse_json(reply.content)
        return RevisionDraft(
            text=(payload.get("text") or "").strip(),
            changed=bool(payload.get("changed")),
            explanation=(payload.get("explanation") or "").strip(),
            provider=self.name,
            model=self.model,
        )


#: The gateway's chat endpoint has no structured-output field, so the JSON
#: contract travels in the system turn and is parsed strictly on return.
JSON_OUTPUT_INSTRUCTION = """\

Return a single JSON object and nothing else — no prose, no code fence — with
exactly these keys:

  "text"        the replacement text for the section
  "changed"     false if the instruction cannot be met without breaking a rule
  "explanation" one sentence on what changed, or why it could not be
"""

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json(content: str) -> dict:
    cleaned = _JSON_FENCE.sub("", content.strip()).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RevisionError(f"secure gateway returned non-JSON revision output: {exc}") from exc
    if not isinstance(payload, dict):
        raise RevisionError("secure gateway returned a revision that is not a JSON object")
    return payload


def get_revision_provider(name: str | None = None) -> RevisionProvider:
    """Resolve the configured reviser. Never substitutes a different boundary."""
    settings = get_settings()
    resolved = (name or settings.llm_provider).lower()
    if resolved == "secure_gateway":
        if not settings.secure_gateway_api_key:
            raise RevisionError(
                "DLG_LLM_PROVIDER=secure_gateway but SECURE_GATEWAY_API_KEY is not set"
            )
        return SecureGatewayRevisionProvider()
    if resolved == "anthropic":
        # Explicit opt-in. Bypasses the privacy gateway; never chosen as a
        # fallback when the gateway is unavailable.
        if not settings.anthropic_api_key:
            raise RevisionError("DLG_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        return AnthropicRevisionProvider()
    if resolved == "stub":
        return RhetoricalStubProvider()
    raise RevisionError(f"unknown revision provider {resolved!r}")

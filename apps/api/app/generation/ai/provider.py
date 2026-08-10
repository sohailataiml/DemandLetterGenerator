"""LLM provider abstraction for narrative drafting.

Two implementations ship:

* :class:`GroundedStubProvider` — deterministic, offline, and incapable of
  inventing anything: it assembles sentences directly from verified fact
  summaries. This is the default, and it is what the test suite runs against.
* :class:`AnthropicProvider` — Claude via the official SDK, with structured
  output and the grounding prompt contract.

Either way the result is re-validated against the fact store downstream; the
provider is a drafting assistant, never the source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from ...config import get_settings
from .prompts import PROMPT_VERSION, RESULT_SCHEMA, SYSTEM_PROMPT, SectionSpec, build_user_prompt


class ProviderError(RuntimeError):
    """The provider could not produce a usable draft."""


@dataclass(frozen=True)
class FactPayload:
    id: str
    fact_type: str
    summary: str
    value: dict[str, Any]
    citations: list[str] = field(default_factory=list)

    def render(self) -> str:
        cites = f" [sources: {', '.join(self.citations)}]" if self.citations else ""
        return f"- {self.id} ({self.fact_type}): {self.summary}{cites}"


@dataclass(frozen=True)
class NarrativeRequest:
    spec: SectionSpec
    context_block: str
    facts: list[FactPayload]

    def facts_block(self) -> str:
        if not self.facts:
            return "(none)"
        return "\n".join(fact.render() for fact in self.facts)


@dataclass(frozen=True)
class NarrativeResult:
    section_key: str
    text: str
    used_fact_ids: list[str]
    insufficient_evidence: bool
    provider: str
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    missing: str | None = None


class LLMProvider(Protocol):
    name: str
    model: str | None

    def draft(self, request: NarrativeRequest) -> NarrativeResult: ...


class GroundedStubProvider:
    """Deterministic drafter used offline and in tests.

    It cannot hallucinate because it only ever concatenates fact summaries it was
    handed. Prose quality is modest by design; correctness is the point.
    """

    name = "stub"
    model = None

    def draft(self, request: NarrativeRequest) -> NarrativeResult:
        if not request.facts:
            return NarrativeResult(
                section_key=request.spec.key,
                text="",
                used_fact_ids=[],
                insufficient_evidence=True,
                provider=self.name,
                missing=(
                    f"No verified facts of type {', '.join(request.spec.fact_types)} are on file, "
                    "so this section cannot be drafted."
                ),
            )
        sentences = []
        for fact in request.facts:
            summary = fact.summary.strip()
            if summary and not summary.endswith("."):
                summary += "."
            sentences.append(summary)
        return NarrativeResult(
            section_key=request.spec.key,
            text=" ".join(sentences),
            used_fact_ids=[fact.id for fact in request.facts],
            insufficient_evidence=False,
            provider=self.name,
        )


class AnthropicProvider:
    """Claude-backed drafter using structured outputs and adaptive thinking."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.anthropic_model
        self._effort = settings.anthropic_effort
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ProviderError(
                "the 'anthropic' package is not installed; "
                "run `pip install anthropic` or set DLG_LLM_PROVIDER=stub"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

    def draft(self, request: NarrativeRequest) -> NarrativeResult:  # pragma: no cover - network
        response = self._client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": RESULT_SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": build_user_prompt(
                        spec=request.spec,
                        context_block=request.context_block,
                        facts_block=request.facts_block(),
                    ),
                }
            ],
        )

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise ProviderError(f"model declined to draft this section (category={category!r})")
        if response.stop_reason == "max_tokens":
            raise ProviderError("draft was truncated at max_tokens; raise the limit and retry")

        text_block = next((b for b in response.content if b.type == "text"), None)
        if text_block is None:
            raise ProviderError("model returned no text block")
        try:
            payload = json.loads(text_block.text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"model returned non-JSON output: {exc}") from exc

        return NarrativeResult(
            section_key=payload.get("section") or request.spec.key,
            text=(payload.get("text") or "").strip(),
            used_fact_ids=list(payload.get("used_fact_ids") or []),
            insufficient_evidence=bool(payload.get("insufficient_evidence")),
            provider=self.name,
            model=self.model,
            missing=payload.get("missing") or None,
        )


def get_provider(name: str | None = None) -> LLMProvider:
    settings = get_settings()
    resolved = (name or settings.llm_provider).lower()
    if resolved == "anthropic":
        if not settings.anthropic_api_key:
            raise ProviderError(
                "DLG_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set"
            )
        return AnthropicProvider()
    if resolved == "stub":
        return GroundedStubProvider()
    raise ProviderError(f"unknown LLM provider {resolved!r}")

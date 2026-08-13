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
    """The provider could not produce a usable revision."""


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


def get_revision_provider(name: str | None = None) -> RevisionProvider:
    settings = get_settings()
    resolved = (name or settings.llm_provider).lower()
    if resolved == "anthropic":
        if not settings.anthropic_api_key:
            raise RevisionError("DLG_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        return AnthropicRevisionProvider()
    if resolved == "stub":
        return RhetoricalStubProvider()
    raise RevisionError(f"unknown revision provider {resolved!r}")

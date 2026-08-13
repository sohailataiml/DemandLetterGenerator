"""Deciding whether a claim is backed by the verified fact store.

This is deliberately not "ask a model whether the text is hallucinated". A
model asked to grade its own output grades it generously, and a second model
asked the same question has no more access to the evidence than the first. The
verdict here is arithmetic over the verified facts: how much of the claim's
content is present in facts an attorney has actually verified.

Two independent checks run per claim.

**Coverage.** What share of the claim's content words appear in the facts it is
allowed to draw on. High coverage means the claim is restating verified
material; low coverage means it is asserting something the evidence does not.

**Escalation.** Some words assert more than the words around them — permanence,
causation, degree, prognosis. A claim may score high on coverage and still say
something the record never said, because it added "permanent" to a finding that
was merely observed. Those terms must appear in the supporting evidence itself,
not merely be surrounded by words that do.

Limits, stated plainly: coverage is lexical, so a paraphrase using entirely
different vocabulary scores low and is flagged for review rather than silently
accepted. That is the safe direction to be wrong in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..domain.enums import ClaimStatus, FactStatus
from ..domain.models import Fact
from .claims import Claim

#: Coverage at or above this reads as "this claim restates verified material".
SUPPORT_THRESHOLD = 0.62
#: Below this there is not enough shared content to call it supported at all.
PARTIAL_THRESHOLD = 0.35
#: Claims shorter than this carry no checkable content (headings, connectives).
MIN_CONTENT_TOKENS = 3

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-/]*")

#: Words that carry no assertion and so should not count toward coverage.
STOPWORDS = frozenset(
    """
    a an and are as at be been being but by for from had has have he her him his
    in into is it its of on or our she that the their them there these they this
    those to was were which who whom will with would you your our us we i
    following also both each more most other some such than then when where
    while after before during about above below over under again further once
    """.split()
)

#: Assertions that must be present in the evidence, not inferred around it.
ESCALATION_TERMS: dict[str, tuple[str, ...]] = {
    "permanence": (
        "permanent", "permanently", "permanence", "lifelong", "life-long",
        "irreversible", "never recover", "will never", "for the rest of",
        "residual permanent",
    ),
    "causation": (
        "caused by", "was caused", "causation", "directly resulted",
        "as a direct result", "attributable to", "due solely to",
    ),
    "prognosis": (
        "will require", "will need", "prognosis", "expected to worsen",
        "degenerative course", "future surgery", "surgery will",
    ),
    "degree": (
        "catastrophic", "debilitating", "totally disabled", "complete loss",
        "severe and permanent", "grave",
    ),
}

#: Markers that turn an assertion into its opposite.
NEGATIONS = ("no ", "not ", "never ", "denies ", "without ", "absence of ", "ruled out")


@dataclass(frozen=True)
class ClaimVerdict:
    claim: Claim
    status: ClaimStatus
    score: float
    fact_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    reason: str = ""
    escalations: tuple[str, ...] = ()
    #: Statuses of the facts this claim leans on — drives CLAIM_002 and CLAIM_004.
    fact_statuses: tuple[str, ...] = ()

    @property
    def is_supported(self) -> bool:
        return self.status == ClaimStatus.SUPPORTED

    def to_dict(self) -> dict:
        return {
            "text": self.claim.text,
            "start_offset": self.claim.start_offset,
            "end_offset": self.claim.end_offset,
            "position": self.claim.position,
            "status": self.status.value,
            "score": self.score,
            "fact_ids": list(self.fact_ids),
            "citation_ids": list(self.citation_ids),
            "reason": self.reason,
            "escalations": list(self.escalations),
        }


@dataclass
class GroundingContext:
    """The evidence a claim may be checked against."""

    facts: Sequence[Fact]
    #: Deterministic literals the template layer is entitled to state.
    known_literals: frozenset[str] = frozenset()
    _index: dict[str, frozenset[str]] = field(default_factory=dict, init=False, repr=False)
    _text: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        for fact in self.facts:
            body = fact_text(fact)
            self._text[fact.id] = body
            self._index[fact.id] = content_tokens(body)

    def tokens_for(self, fact_id: str) -> frozenset[str]:
        return self._index.get(fact_id, frozenset())

    def text_for(self, fact_id: str) -> str:
        return self._text.get(fact_id, "")

    def fact(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fact_id), None)


def fact_text(fact: Fact) -> str:
    """Everything a fact asserts, flattened for lexical comparison."""
    parts = [fact.summary or ""]
    try:
        parts.append(json.dumps(fact.value, default=str))
    except (TypeError, ValueError):  # pragma: no cover - JSON column guarantees this
        parts.append(str(fact.value))
    for source in fact.sources:
        if source.excerpt:
            parts.append(source.excerpt)
    return " ".join(parts)


def content_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token for token in _TOKEN.findall(text.lower()) if token not in STOPWORDS
    )


def _coverage(claim_tokens: frozenset[str], evidence: frozenset[str]) -> float:
    if not claim_tokens:
        return 1.0
    return len(claim_tokens & evidence) / len(claim_tokens)


def _escalations_in(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    found = [
        category
        for category, terms in ESCALATION_TERMS.items()
        if any(term in lowered for term in terms)
    ]
    return tuple(sorted(set(found)))


def _escalation_terms_in(text: str) -> set[str]:
    lowered = text.lower()
    return {
        term
        for terms in ESCALATION_TERMS.values()
        for term in terms
        if term in lowered
    }


def _contradicts(claim_text: str, evidence_text: str) -> bool:
    """A narrow, honest contradiction check.

    It only fires when the claim negates a phrase the evidence states plainly.
    General contradiction detection is not something this system claims to do;
    what it does is refuse to let "no fracture" pass while the record says
    "fracture" and nothing else in the claim differs.
    """
    lowered_claim = claim_text.lower()
    lowered_evidence = evidence_text.lower()
    for negation in NEGATIONS:
        for match in re.finditer(re.escape(negation), lowered_claim):
            tail = lowered_claim[match.end() : match.end() + 60]
            subject = next(iter(_TOKEN.findall(tail)), None)
            if not subject or subject in STOPWORDS or len(subject) < 4:
                continue
            if subject in lowered_evidence and negation not in lowered_evidence:
                return True
    return False


def check_claim(
    claim: Claim, context: GroundingContext, candidate_fact_ids: Iterable[str]
) -> ClaimVerdict:
    """Grade one claim against the facts it is permitted to rely on."""
    claim_tokens = content_tokens(claim.text)
    candidates = [fid for fid in candidate_fact_ids if context.fact(fid) is not None]

    if len(claim_tokens) < MIN_CONTENT_TOKENS or claim_tokens <= context.known_literals:
        # Connective or boilerplate text asserts nothing to check.
        return ClaimVerdict(
            claim=claim,
            status=ClaimStatus.SUPPORTED,
            score=1.0,
            reason="no checkable factual content",
        )

    combined: frozenset[str] = frozenset()
    per_fact: list[tuple[str, float]] = []
    for fact_id in candidates:
        tokens = context.tokens_for(fact_id)
        combined |= tokens
        per_fact.append((fact_id, _coverage(claim_tokens, tokens)))

    # Deterministic literals the letter is entitled to state (names, dates,
    # figures the calculator produced) count as evidence, because they are.
    evidence = combined | context.known_literals
    score = round(_coverage(claim_tokens, evidence), 4)

    supporting = tuple(fid for fid, fact_score in sorted(per_fact, key=lambda p: -p[1])
                       if fact_score > 0)
    citation_ids = tuple(
        source.id
        for fid in supporting
        for source in (context.fact(fid).sources if context.fact(fid) else [])
    )
    statuses = tuple(str(context.fact(fid).status) for fid in supporting if context.fact(fid))

    evidence_text = " ".join(context.text_for(fid) for fid in supporting)

    # A contradiction outranks coverage: restating the evidence and then
    # negating it scores well and is still wrong.
    if supporting and _contradicts(claim.text, evidence_text):
        return ClaimVerdict(
            claim=claim,
            status=ClaimStatus.UNSUPPORTED,
            score=score,
            fact_ids=supporting,
            citation_ids=citation_ids,
            fact_statuses=statuses,
            reason="the claim negates something the verified evidence states",
        )

    escalations = _escalations_in(claim.text)
    if escalations:
        claimed_terms = _escalation_terms_in(claim.text)
        evidence_terms = _escalation_terms_in(evidence_text)
        unsupported_terms = sorted(claimed_terms - evidence_terms)
        if unsupported_terms:
            return ClaimVerdict(
                claim=claim,
                status=ClaimStatus.UNSUPPORTED,
                score=score,
                fact_ids=supporting,
                citation_ids=citation_ids,
                escalations=escalations,
                fact_statuses=statuses,
                reason=(
                    "the claim asserts "
                    + ", ".join(unsupported_terms)
                    + " which the verified evidence does not establish"
                ),
            )

    if score >= SUPPORT_THRESHOLD:
        status = ClaimStatus.SUPPORTED
        reason = ""
    elif score >= PARTIAL_THRESHOLD:
        status = ClaimStatus.PARTIALLY_SUPPORTED
        reason = "only part of this claim is present in the verified evidence"
    else:
        status = ClaimStatus.UNSUPPORTED
        reason = (
            "no verified fact covers this assertion"
            if not supporting
            else "the cited facts do not cover what this claim asserts"
        )

    return ClaimVerdict(
        claim=claim,
        status=status,
        score=score,
        fact_ids=supporting,
        citation_ids=citation_ids,
        escalations=escalations,
        fact_statuses=statuses,
        reason=reason,
    )


def stale_fact_ids(facts: Sequence[Fact]) -> frozenset[str]:
    """Facts that exist but may not support anything: not VERIFIED, or superseded."""
    return frozenset(
        fact.id
        for fact in facts
        if fact.status != FactStatus.VERIFIED or fact.superseded_by_id
    )

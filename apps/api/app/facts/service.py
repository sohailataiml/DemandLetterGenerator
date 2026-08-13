"""Fact lifecycle: PROPOSED → VERIFIED / REJECTED, with supersession.

Three invariants hold the provenance story together:

1. Anything a model extracts lands as ``PROPOSED``. Nothing verifies itself.
2. A fact cannot be verified without at least one document/page citation.
3. A ``VERIFIED`` fact is never edited. Corrections create a new revision that
   supersedes it, so what an attorney approved stays on the record.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import service as audit
from ..domain.enums import FactStatus, FactType
from ..domain.models import Fact, FactSource, SourceDocument
from ..domain.schemas import FactSourceIn
from ..provenance import citations
from ..security.auth import CurrentUser


class FactStateError(ValueError):
    """An operation was attempted that the fact's current state forbids."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _page_text(document: SourceDocument, page_number: int | None) -> str:
    if page_number is None:
        return ""
    page = next((p for p in document.pages if p.page_number == page_number), None)
    return page.text if page else ""


def _attach_sources(
    session: Session, fact: Fact, sources: list[FactSourceIn], case_id: str
) -> None:
    """Attach citations, resolving each excerpt to a span where possible.

    A hand-entered citation gets the same treatment as an extracted one: the
    excerpt is looked up in the stored page text so the reviewer's highlight is
    a real offset rather than a search the UI has to redo. An excerpt that
    cannot be located is still stored — a paralegal paraphrasing a record is
    legitimate — but it is recorded without offsets so the UI can say the
    highlight is approximate instead of implying precision it does not have.
    """
    for source in sources:
        document = session.get(SourceDocument, source.document_id)
        if document is None or document.case_id != case_id:
            raise FactStateError(f"source document {source.document_id!r} is not part of this case")
        if source.page_number is not None and not (1 <= source.page_number <= document.page_count):
            raise FactStateError(
                f"page {source.page_number} is outside document {document.id} "
                f"(1..{document.page_count})"
            )

        resolved = None
        if source.excerpt:
            resolved = citations.resolve(_page_text(document, source.page_number), source.excerpt)

        session.add(
            FactSource(
                fact_id=fact.id,
                document_id=source.document_id,
                page_number=source.page_number,
                excerpt=source.excerpt,
                start_offset=resolved.start_offset if resolved else None,
                end_offset=resolved.end_offset if resolved else None,
                quoted_text_sha256=resolved.quoted_text_sha256 if resolved else None,
                match_kind=resolved.match_kind.value if resolved else None,
            )
        )


def propose_fact(
    session: Session,
    *,
    case_id: str,
    fact_type: FactType,
    value: dict,
    summary: str,
    sources: list[FactSourceIn],
    actor: CurrentUser | str,
    confidence: float | None = None,
    revision: int = 1,
    supersedes: Fact | None = None,
) -> Fact:
    proposer = actor.id if isinstance(actor, CurrentUser) else actor
    fact = Fact(
        case_id=case_id,
        fact_type=fact_type,
        value=value,
        summary=summary,
        status=FactStatus.PROPOSED,
        confidence=confidence,
        revision=revision,
        supersedes_id=supersedes.id if supersedes else None,
        proposed_by=proposer,
    )
    session.add(fact)
    session.flush()
    _attach_sources(session, fact, sources, case_id)

    audit.record(
        session,
        event="FACT_PROPOSED",
        actor=actor,
        case_id=case_id,
        subject_id=fact.id,
        payload={"fact_type": fact_type.value, "summary": summary, "revision": revision},
    )
    session.flush()
    return fact


def verify_fact(session: Session, fact: Fact, actor: CurrentUser) -> Fact:
    if fact.status != FactStatus.PROPOSED:
        raise FactStateError(f"only PROPOSED facts can be verified; {fact.id} is {fact.status}")
    if not fact.sources:
        raise FactStateError(
            "a fact cannot be verified without at least one source document citation"
        )
    fact.status = FactStatus.VERIFIED
    fact.reviewed_by = actor.id
    fact.reviewed_at = _now()

    if fact.supersedes_id:
        previous = session.get(Fact, fact.supersedes_id)
        if previous is not None:
            previous.status = FactStatus.SUPERSEDED
            previous.superseded_by_id = fact.id

    audit.record(
        session,
        event="FACT_VERIFIED",
        actor=actor,
        case_id=fact.case_id,
        subject_id=fact.id,
        payload={
            "summary": fact.summary,
            "revision": fact.revision,
            "supersedes": fact.supersedes_id,
        },
    )
    session.flush()
    return fact


def reject_fact(session: Session, fact: Fact, actor: CurrentUser, reason: str) -> Fact:
    if fact.status != FactStatus.PROPOSED:
        raise FactStateError(f"only PROPOSED facts can be rejected; {fact.id} is {fact.status}")
    fact.status = FactStatus.REJECTED
    fact.reviewed_by = actor.id
    fact.reviewed_at = _now()
    fact.rejection_reason = reason

    audit.record(
        session,
        event="FACT_REJECTED",
        actor=actor,
        case_id=fact.case_id,
        subject_id=fact.id,
        payload={"reason": reason},
    )
    session.flush()
    return fact


def supersede_fact(
    session: Session,
    fact: Fact,
    *,
    fact_type: FactType,
    value: dict,
    summary: str,
    sources: list[FactSourceIn],
    reason: str,
    actor: CurrentUser,
) -> Fact:
    """Create the next revision of a verified fact. The original is untouched
    until the replacement is itself verified."""
    if fact.status not in (FactStatus.VERIFIED, FactStatus.PROPOSED):
        raise FactStateError(f"cannot supersede a {fact.status} fact; only VERIFIED or PROPOSED")
    if fact.superseded_by_id:
        raise FactStateError(f"{fact.id} has already been superseded by {fact.superseded_by_id}")

    replacement = propose_fact(
        session,
        case_id=fact.case_id,
        fact_type=fact_type,
        value=value,
        summary=summary,
        sources=sources,
        actor=actor,
        revision=fact.revision + 1,
        supersedes=fact,
    )
    audit.record(
        session,
        event="FACT_SUPERSEDE_PROPOSED",
        actor=actor,
        case_id=fact.case_id,
        subject_id=replacement.id,
        payload={"supersedes": fact.id, "reason": reason},
    )
    session.flush()
    return replacement


def verified_facts(session: Session, case_id: str) -> list[Fact]:
    stmt = (
        select(Fact)
        .where(Fact.case_id == case_id, Fact.status == FactStatus.VERIFIED)
        .order_by(Fact.fact_type, Fact.created_at)
    )
    return list(session.scalars(stmt))


def list_facts(
    session: Session, case_id: str, status: FactStatus | None = None
) -> list[Fact]:
    stmt = select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at)
    if status is not None:
        stmt = stmt.where(Fact.status == status)
    return list(session.scalars(stmt))

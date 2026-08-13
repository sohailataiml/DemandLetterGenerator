"""AI extraction proposes facts. It never puts one into evidence."""

from __future__ import annotations

import pytest

import golden
from app.extraction import chunker, service
from app.extraction.prompts import ExtractionRequest
from app.extraction.provider import Candidate, ExtractionResponse, PatternExtractor
from conftest import ATTORNEY, PARALEGAL, upload_text_document

MATERIALS = {
    path.name: path.read_text(encoding="utf-8")
    for path in sorted(golden.MATERIALS_DIR.glob("*.txt"))
}


class _FabricatingProvider:
    """A provider that quotes text the document does not contain."""

    name = "fabricating"
    model = "test"

    def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        return ExtractionResponse(
            candidates=(
                Candidate(
                    fact_type="diagnosis",
                    summary="The collision caused permanent nerve damage",
                    value={"permanence": True},
                    quote="Permanent nerve damage is certain and irreversible.",
                    confidence=0.99,
                ),
            )
        )


class _MistypedProvider:
    name = "mistyped"
    model = None

    def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        return ExtractionResponse(
            candidates=(
                Candidate(
                    fact_type="settlement_authority",  # not a FactType
                    summary="The adjuster has authority to pay policy limits",
                    value={},
                    quote=request.text[:60],
                    confidence=0.9,
                ),
            )
        )


# --------------------------------------------------------------------------- chunking


def test_a_short_page_is_one_chunk():
    chunks = chunker.split_page(1, "A short page of text.")
    assert len(chunks) == 1
    assert chunks[0].page_offset == 0


def test_an_empty_page_produces_no_chunks():
    assert chunker.split_page(1, "   \n\n  ") == []


def test_a_long_page_splits_on_paragraph_boundaries_with_correct_offsets():
    page = "\n\n".join(f"Paragraph number {i}. " + ("filler " * 40) for i in range(20))
    chunks = chunker.split_page(1, page, max_chars=1200)

    assert len(chunks) > 1
    for chunk in chunks:
        # The offset must actually index the page, or a citation built from a
        # chunk quote would point at the wrong words.
        assert page[chunk.page_offset : chunk.end_offset] == chunk.text
    assert "".join(c.text for c in chunks) == page


# ------------------------------------------------------------------- pattern reading


@pytest.mark.parametrize(
    "material,expected_type",
    [
        ("police-report.txt", "liability"),
        ("chiropractic-records.txt", "diagnosis"),
        ("mri-report.txt", "imaging_finding"),
        ("billing-summary.txt", "medical_expense"),
    ],
)
def test_the_pattern_extractor_reads_each_kind_of_material(material, expected_type):
    response = PatternExtractor().extract(
        ExtractionRequest(
            document_id="doc_1",
            document_type="OTHER",
            page_number=1,
            chunk_index=0,
            page_offset=0,
            text=MATERIALS[material],
        )
    )
    assert expected_type in {c.fact_type for c in response.candidates}


def test_every_pattern_candidate_quotes_the_document_verbatim():
    for text in MATERIALS.values():
        response = PatternExtractor().extract(
            ExtractionRequest(
                document_id="doc_1",
                document_type="OTHER",
                page_number=1,
                chunk_index=0,
                page_offset=0,
                text=text,
            )
        )
        for candidate in response.candidates:
            assert candidate.quote in text


def test_a_bill_with_no_amount_yields_no_expense_fact():
    """INVARIANT-004 — 'NOT YET RECEIVED' must not become a number."""
    response = PatternExtractor().extract(
        ExtractionRequest(
            document_id="doc_1",
            document_type="BILL",
            page_number=1,
            chunk_index=0,
            page_offset=0,
            text=MATERIALS["billing-summary.txt"],
        )
    )
    expenses = [c for c in response.candidates if c.fact_type == "medical_expense"]
    providers = {c.value.get("provider") for c in expenses}
    assert "Harbor Pain Management" not in providers
    assert all("0.00" != c.value.get("amount") for c in expenses)


# -------------------------------------------------------------------- the whole run


@pytest.fixture
def case_with_materials(client, seeded_case):
    case_id = seeded_case["case_id"]
    documents = {
        name: upload_text_document(client, case_id, name, body)
        for name, body in MATERIALS.items()
    }
    return {"case_id": case_id, "documents": documents}


def test_extraction_creates_only_proposed_facts(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    response = client.post(f"/v1/cases/{case_id}/extract", json={}, headers=ATTORNEY)
    assert response.status_code == 202, response.text
    reports = response.json()
    assert sum(r["proposed"] for r in reports) > 0

    facts = client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
    assert facts
    assert {fact["status"] for fact in facts} == {"PROPOSED"}


def test_every_proposed_fact_carries_a_resolvable_span(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    client.post(f"/v1/cases/{case_id}/extract", json={}, headers=ATTORNEY)

    facts = client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
    for fact in facts:
        assert fact["sources"], f"{fact['id']} has no citation"
        for source in fact["sources"]:
            assert source["page_number"] is not None
            assert source["start_offset"] is not None
            assert source["end_offset"] > source["start_offset"]
            assert source["quoted_text_sha256"]
            assert source["match_kind"] in ("exact", "normalized", "approximate")


def test_the_recorded_span_quotes_the_stored_page(client, case_with_materials):
    from app.provenance import citations

    case_id = case_with_materials["case_id"]
    client.post(f"/v1/cases/{case_id}/extract", json={}, headers=ATTORNEY)
    facts = client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()

    pages: dict[str, dict[int, str]] = {}
    for fact in facts:
        for source in fact["sources"]:
            document_id = source["document_id"]
            if document_id not in pages:
                detail = client.get(f"/v1/documents/{document_id}", headers=ATTORNEY).json()
                pages[document_id] = {p["page_number"]: p["text"] for p in detail["pages"]}
            text = pages[document_id][source["page_number"]]
            assert citations.verify_offsets(
                text, source["start_offset"], source["end_offset"], source["quoted_text_sha256"]
            )


def test_extraction_records_its_own_provenance(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    client.post(f"/v1/cases/{case_id}/extract", json={}, headers=ATTORNEY)

    facts = client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
    metadata = facts[0]["extraction_metadata"]
    assert metadata["provider"] == "pattern"
    assert metadata["prompt_version"] == "extraction_v1"
    assert metadata["document_id"]
    assert metadata["page_number"] == 1
    assert facts[0]["proposed_by"].startswith("pattern:")


def test_a_fabricated_quote_never_becomes_a_fact(client, case_with_materials, db):
    """The deterministic gate: no evidence, no fact."""
    from app.domain.models import SourceDocument
    from app.security.auth import CurrentUser
    from app.domain.enums import UserRole

    case_id = case_with_materials["case_id"]
    document_id = case_with_materials["documents"]["mri-report.txt"]["id"]
    document = db.get(SourceDocument, document_id)
    actor = CurrentUser(id="attorney_45", role=UserRole.ATTORNEY)

    report = service.extract_document(
        db, document, actor=actor, provider=_FabricatingProvider()
    )
    assert report.candidates == 1
    assert report.proposed == 0
    assert report.rejected[0]["reason"] == service.NO_CITATION


def test_a_fact_type_this_system_does_not_model_is_rejected(client, case_with_materials, db):
    from app.domain.enums import UserRole
    from app.domain.models import SourceDocument
    from app.security.auth import CurrentUser

    document_id = case_with_materials["documents"]["police-report.txt"]["id"]
    document = db.get(SourceDocument, document_id)
    actor = CurrentUser(id="attorney_45", role=UserRole.ATTORNEY)

    report = service.extract_document(db, document, actor=actor, provider=_MistypedProvider())
    assert report.proposed == 0
    assert report.rejected[0]["reason"] == service.UNKNOWN_TYPE


def test_extraction_can_be_limited_to_named_documents(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    only = case_with_materials["documents"]["mri-report.txt"]["id"]
    response = client.post(
        f"/v1/cases/{case_id}/extract", json={"document_ids": [only]}, headers=ATTORNEY
    )
    reports = response.json()
    assert [r["document_id"] for r in reports] == [only]


def test_extraction_is_recorded_in_the_audit_trail(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    client.post(f"/v1/cases/{case_id}/extract", json={}, headers=ATTORNEY)

    events = client.get(f"/v1/cases/{case_id}/audit", headers=ATTORNEY).json()
    runs = [e for e in events if e["event"] == "FACTS_EXTRACTED"]
    assert runs
    assert runs[0]["payload"]["provider"] == "pattern"
    assert "proposed_fact_ids" in runs[0]["payload"]


def test_a_paralegal_may_run_extraction_but_a_reader_may_not(client, case_with_materials):
    case_id = case_with_materials["case_id"]
    assert (
        client.post(f"/v1/cases/{case_id}/extract", json={}, headers=PARALEGAL).status_code == 202
    )
    assert (
        client.post(
            f"/v1/cases/{case_id}/extract",
            json={},
            headers={"X-User-Id": "viewer_1", "X-User-Role": "readonly"},
        ).status_code
        == 403
    )


def test_extracted_facts_do_not_reach_the_letter_until_verified(client, case_with_materials):
    """INVARIANT-001, at the point it matters most."""
    case_id = case_with_materials["case_id"]
    client.post(f"/v1/cases/{case_id}/extract", json={}, headers=ATTORNEY)

    demand = client.post(f"/v1/cases/{case_id}/demands", json={}, headers=ATTORNEY).json()
    client.post(f"/v1/demands/{demand['id']}/generate", json={}, headers=ATTORNEY)
    detail = client.get(f"/v1/demands/{demand['id']}", headers=ATTORNEY).json()

    proposed = {
        fact["id"]
        for fact in client.get(f"/v1/cases/{case_id}/facts", headers=ATTORNEY).json()
        if fact["status"] == "PROPOSED"
    }
    assert proposed
    used = {fid for section in detail["sections"] for fid in section["used_fact_ids"]}
    assert not (used & proposed)


def test_manually_entered_citations_also_get_spans(client, seeded_case):
    """A paralegal's citation is resolved the same way an extractor's is."""
    case_id = seeded_case["case_id"]
    document = upload_text_document(
        client, case_id, "note.txt", "Patient reports lumbar pain radiating to the right leg."
    )
    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "diagnosis",
            "value": {},
            "summary": "Lumbar pain with right leg radiation is documented",
            "sources": [
                {
                    "document_id": document["id"],
                    "page_number": 1,
                    "excerpt": "lumbar pain radiating to the right leg",
                }
            ],
        },
        headers=ATTORNEY,
    ).json()

    source = fact["sources"][0]
    assert source["match_kind"] == "exact"
    assert source["start_offset"] is not None


def test_a_paraphrased_citation_is_stored_without_false_precision(client, seeded_case):
    case_id = seeded_case["case_id"]
    document = upload_text_document(
        client, case_id, "note2.txt", "Patient reports lumbar pain radiating to the right leg."
    )
    fact = client.post(
        f"/v1/cases/{case_id}/facts",
        json={
            "fact_type": "diagnosis",
            "value": {},
            "summary": "The client has sciatica",
            "sources": [
                {
                    "document_id": document["id"],
                    "page_number": 1,
                    "excerpt": "the claimant suffers from severe chronic sciatica of the lumbar region",
                }
            ],
        },
        headers=ATTORNEY,
    ).json()

    source = fact["sources"][0]
    # Either no span at all, or one explicitly marked approximate — never a
    # precise-looking offset the reviewer would trust.
    assert source["match_kind"] in (None, "approximate")

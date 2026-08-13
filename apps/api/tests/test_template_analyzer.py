"""The analyzer reads an attorney's template without changing it."""

from __future__ import annotations

import io

import pytest
from docx import Document

import golden
from app.templates import analyzer
from app.templates.manifest import SlotKind, TemplateManifest


@pytest.fixture(scope="module")
def template_bytes() -> bytes:
    return golden.TEMPLATE_PATH.read_bytes()


@pytest.fixture(scope="module")
def manifest(template_bytes: bytes):
    return analyzer.analyze(template_bytes)


def test_rejects_a_file_that_is_not_a_docx():
    with pytest.raises(analyzer.TemplateAnalysisError):
        analyzer.analyze(b"this is a text file, not a Word document")


def test_records_every_body_block(manifest):
    assert len(manifest.blocks) > 20
    assert {block.kind for block in manifest.blocks} == {"paragraph", "table"}
    assert all(block.text_sha256 for block in manifest.blocks)


def test_finds_the_headings_as_sections(manifest):
    keys = {section.key for section in manifest.sections}
    assert {"liability", "medical_treatment", "diagnostic_imaging", "medical_expenses"} <= keys


def test_classifies_slots_by_how_they_must_be_bound(manifest):
    by_name = {slot.name: slot for slot in manifest.slots}

    # A placeholder among other text is replaced in place.
    assert by_name["demand_expiration"].kind == SlotKind.INLINE
    assert by_name["client_name"].kind == SlotKind.INLINE

    # A paragraph that is only a placeholder becomes N paragraphs.
    assert by_name["liability_section"].kind == SlotKind.BLOCK

    # A table row with ``collection[].field`` repeats per item.
    expenses = by_name["medical_expenses"]
    assert expenses.kind == SlotKind.ROW
    assert set(expenses.fields) == {"provider", "description", "amount"}
    assert expenses.row_index == 1  # row 0 is the header


def test_records_page_setup_headers_and_footers(manifest):
    assert manifest.page_setup.page_width == 12240
    assert manifest.page_setup.page_height == 15840
    assert manifest.page_setup.margin_left == 1296
    assert [part.name for part in manifest.headers] == ["word/header1.xml"]
    assert [part.name for part in manifest.footers] == ["word/footer1.xml"]
    assert [part.name for part in manifest.styles] == ["word/styles.xml"]
    assert manifest.section_break_count == 2


def test_fingerprint_identifies_the_exact_file(template_bytes, manifest):
    import hashlib

    assert manifest.fingerprint.sha256 == hashlib.sha256(template_bytes).hexdigest()
    assert manifest.fingerprint.byte_size == len(template_bytes)
    assert len(manifest.fingerprint.structure_sha256) == 64


def test_a_changed_template_produces_a_different_fingerprint(template_bytes, manifest):
    document = Document(io.BytesIO(template_bytes))
    document.add_paragraph("An extra clause the firm added later.")
    buffer = io.BytesIO()
    document.save(buffer)

    changed = analyzer.analyze(buffer.getvalue())
    assert changed.fingerprint.sha256 != manifest.fingerprint.sha256
    assert changed.fingerprint.structure_sha256 != manifest.fingerprint.structure_sha256


def test_manifest_survives_a_json_round_trip(manifest):
    import json

    restored = TemplateManifest.from_dict(json.loads(manifest.to_json()))
    assert restored.fingerprint == manifest.fingerprint
    assert restored.slots == manifest.slots
    assert restored.blocks == manifest.blocks
    assert restored.page_setup == manifest.page_setup


def test_immutable_blocks_exclude_every_slot(manifest):
    dynamic = {slot.block_index for slot in manifest.slots}
    assert dynamic
    assert not (manifest.immutable_block_indexes() & dynamic)


def test_analysis_does_not_modify_the_source_bytes(template_bytes):
    before = bytes(template_bytes)
    analyzer.analyze(template_bytes)
    assert template_bytes == before

"""Structural comparison of two .docx files.

Byte comparison is the wrong tool: python-docx stamps a modification time into
``docProps/core.xml`` on every save, so two runs of the same pipeline over the
same data never produce identical bytes. What has to match is everything that
decides how the document looks and what it says.
"""

from __future__ import annotations

import io
import zipfile

from app.templates import analyzer


def _relationships(data: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name for name in archive.namelist() if not name.startswith("docProps/")}


def _block_signature(block) -> tuple:
    return (block.kind, block.style or "", block.text, block.row_count, block.column_count)


def differences(expected: bytes, actual: bytes) -> list[str]:
    """Every way ``actual`` differs from ``expected`` that a reader would notice."""
    left, right = analyzer.analyze(expected), analyzer.analyze(actual)
    found: list[str] = []

    left_parts, right_parts = _relationships(expected), _relationships(actual)
    if left_parts != right_parts:
        missing = sorted(left_parts - right_parts)
        added = sorted(right_parts - left_parts)
        found.append(f"package parts differ: missing={missing} added={added}")

    for label, before, after in [
        ("headers", left.headers, right.headers),
        ("footers", left.footers, right.footers),
        ("styles", left.styles, right.styles),
        ("numbering", left.numbering, right.numbering),
    ]:
        before_map = {p.name: p.sha256 for p in before}
        after_map = {p.name: p.sha256 for p in after}
        if before_map != after_map:
            found.append(f"{label} differ: {sorted(set(before_map) ^ set(after_map)) or 'content'}")

    if left.page_setup != right.page_setup:
        found.append(f"page setup differs: {left.page_setup} != {right.page_setup}")
    if left.section_break_count != right.section_break_count:
        found.append(
            f"section break count differs: {left.section_break_count} "
            f"!= {right.section_break_count}"
        )

    left_blocks = [_block_signature(b) for b in left.blocks]
    right_blocks = [_block_signature(b) for b in right.blocks]
    if len(left_blocks) != len(right_blocks):
        found.append(f"block count differs: {len(left_blocks)} != {len(right_blocks)}")
    for index, (before, after) in enumerate(zip(left_blocks, right_blocks)):
        if before != after:
            found.append(f"block {index} differs:\n  expected {before!r}\n  actual   {after!r}")

    return found


def assert_matches(expected: bytes, actual: bytes) -> None:
    found = differences(expected, actual)
    assert not found, "generated document diverged from the golden document:\n" + "\n".join(found)

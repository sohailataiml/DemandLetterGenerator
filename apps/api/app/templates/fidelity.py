"""Proves that binding changed only what it was allowed to change.

The check is a comparison of two manifests: the one describing the attorney's
template, and one produced by re-analyzing the document that came out of the
binder. Anything the template marked immutable has to still be there, in the
same order, with the same text — and the parts that carry formatting (styles,
numbering, headers, footers, page setup) have to be byte-identical.

This module deliberately has no dependency on the validation engine. It emits
plain :class:`FidelityIssue` records; :mod:`app.validation.rules` adapts them
into the engine's issues so they gate approval like every other rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .analyzer import analyze
from .manifest import PartDigest, TemplateManifest

BLOCKING = "BLOCKING"
WARNING = "WARNING"

TEMPLATE_SECTION_ORDER = "TEMPLATE_001"
TEMPLATE_BLOCK_MISSING = "TEMPLATE_002"
TEMPLATE_HEADER_FOOTER = "TEMPLATE_003"
TEMPLATE_PAGE_SETUP = "TEMPLATE_004"
TEMPLATE_STYLES = "TEMPLATE_005"
TEMPLATE_TABLE = "TEMPLATE_006"
TEMPLATE_PAGINATION = "TEMPLATE_007"
TEMPLATE_OOXML_BLOCK = "TEMPLATE_008"
TEMPLATE_UNRESOLVED = "TEMPLATE_009"


@dataclass(frozen=True)
class FidelityIssue:
    code: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.severity == BLOCKING

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class FidelityReport:
    template_hash: str
    required_blocks_expected: int
    required_blocks_preserved: int
    styles_changed: int
    headers_changed: int
    footers_changed: int
    numbering_changed: int
    page_setup_changed: bool
    issues: tuple[FidelityIssue, ...] = ()

    @property
    def blocking_issues(self) -> tuple[FidelityIssue, ...]:
        return tuple(i for i in self.issues if i.is_blocking)

    @property
    def is_faithful(self) -> bool:
        return not self.blocking_issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_hash": self.template_hash,
            "required_blocks": {
                "expected": self.required_blocks_expected,
                "preserved": self.required_blocks_preserved,
            },
            "styles_changed": self.styles_changed,
            "headers_changed": self.headers_changed,
            "footers_changed": self.footers_changed,
            "numbering_changed": self.numbering_changed,
            "page_setup_changed": self.page_setup_changed,
            "blocking_issues": [i.to_dict() for i in self.blocking_issues],
            "warnings": [i.to_dict() for i in self.issues if not i.is_blocking],
        }


# --------------------------------------------------------------------------- helpers


def _signature(block) -> tuple[str, str, str]:
    return (block.kind, block.style or "", block.text_sha256)


def _immutable_signatures(manifest: TemplateManifest) -> list[tuple[str, str, str]]:
    dynamic = {slot.block_index for slot in manifest.slots}
    return [_signature(b) for b in manifest.blocks if b.index not in dynamic]


def _longest_ordered_match(
    expected: Sequence[tuple[str, str, str]], actual: Sequence[tuple[str, str, str]]
) -> tuple[dict[int, int], list[int]]:
    """Greedy in-order match of ``expected`` against ``actual``.

    Returns ``(expected position -> actual index)`` for everything found in
    order, and the positions that were not. Greedy is sufficient here because
    template blocks carry distinct text; it never over-reports a preserved
    block.
    """
    cursor = 0
    matched: dict[int, int] = {}
    unmatched: list[int] = []
    for position, signature in enumerate(expected):
        found = -1
        for index in range(cursor, len(actual)):
            if actual[index] == signature:
                found = index
                break
        if found == -1:
            unmatched.append(position)
        else:
            matched[position] = found
            cursor = found + 1
    return matched, unmatched


def _search_window(
    position: int, matched: dict[int, int], total_actual: int
) -> tuple[int, int]:
    """Where in the output an unmatched expected block would have to live.

    Bounded by the nearest matched neighbours on either side, so a modified
    block is looked for only where the template put it.
    """
    before = [matched[p] for p in matched if p < position]
    after = [matched[p] for p in matched if p > position]
    return (max(before) + 1 if before else 0, min(after) if after else total_actual)


def _digest_map(parts: Sequence[PartDigest]) -> dict[str, str]:
    return {part.name: part.sha256 for part in parts}


def _compare_parts(
    label: str, code: str, before: Sequence[PartDigest], after: Sequence[PartDigest]
) -> tuple[int, list[FidelityIssue]]:
    left, right = _digest_map(before), _digest_map(after)
    changed = 0
    issues: list[FidelityIssue] = []
    for name in sorted(set(left) | set(right)):
        if left.get(name) == right.get(name):
            continue
        changed += 1
        if name not in right:
            reason = "removed from the generated document"
        elif name not in left:
            reason = "added to the generated document"
        else:
            reason = "content differs from the template"
        issues.append(
            FidelityIssue(
                code=code,
                severity=BLOCKING,
                message=f"{label} part '{name}' {reason}.",
                details={"part": name, "template_sha256": left.get(name),
                         "generated_sha256": right.get(name)},
            )
        )
    return changed, issues


# --------------------------------------------------------------------------- checks


def _check_blocks(
    template: TemplateManifest, generated: TemplateManifest
) -> tuple[int, int, list[FidelityIssue]]:
    expected = _immutable_signatures(template)
    actual = [_signature(b) for b in generated.blocks]
    matched, unmatched = _longest_ordered_match(expected, actual)

    issues: list[FidelityIssue] = []
    if unmatched:
        present_anywhere = set(actual)
        consumed = set(matched.values())
        missing_entirely: list[int] = []
        altered: list[int] = []
        reordered: list[int] = []
        for position in unmatched:
            signature = expected[position]
            if signature in present_anywhere:
                # The block survived, but somewhere else in the document.
                reordered.append(position)
                continue
            # Where the template says it should be, is there a block of the same
            # kind and style carrying different text? Then it was edited, not lost.
            low, high = _search_window(position, matched, len(actual))
            replaced = any(
                index not in consumed and actual[index][:2] == signature[:2]
                for index in range(low, high)
            )
            (altered if replaced else missing_entirely).append(position)

        if reordered:
            issues.append(
                FidelityIssue(
                    code=TEMPLATE_SECTION_ORDER,
                    severity=BLOCKING,
                    message=(
                        f"{len(reordered)} template block(s) are present but no longer in the "
                        "order the template defines."
                    ),
                    details={"positions": reordered},
                )
            )
        if altered:
            issues.append(
                FidelityIssue(
                    code=TEMPLATE_OOXML_BLOCK,
                    severity=BLOCKING,
                    message=(
                        f"{len(altered)} immutable template block(s) were modified during binding."
                    ),
                    details={"positions": altered},
                )
            )
        if missing_entirely:
            issues.append(
                FidelityIssue(
                    code=TEMPLATE_BLOCK_MISSING,
                    severity=BLOCKING,
                    message=(
                        f"{len(missing_entirely)} required template block(s) are absent from the "
                        "generated document."
                    ),
                    details={"positions": missing_entirely},
                )
            )
    return len(expected), len(matched), issues


def _check_page_setup(
    template: TemplateManifest, generated: TemplateManifest
) -> tuple[bool, list[FidelityIssue]]:
    before, after = template.page_setup.to_dict(), generated.page_setup.to_dict()
    differences = {k: (before[k], after[k]) for k in before if before[k] != after.get(k)}
    if not differences and template.section_break_count == generated.section_break_count:
        return False, []
    if template.section_break_count != generated.section_break_count:
        differences["section_break_count"] = (
            template.section_break_count,
            generated.section_break_count,
        )
    return True, [
        FidelityIssue(
            code=TEMPLATE_PAGE_SETUP,
            severity=BLOCKING,
            message="Page setup differs from the template: "
            + ", ".join(sorted(differences)) + ".",
            details={"differences": {k: list(v) for k, v in differences.items()}},
        )
    ]


def _check_tables(
    template: TemplateManifest, generated: TemplateManifest
) -> list[FidelityIssue]:
    """Tables with no ROW slot must keep their shape exactly."""
    row_slot_blocks = {
        slot.block_index for slot in template.slots if slot.kind.value == "row"
    }
    protected = [
        b
        for b in template.blocks
        if b.kind == "table" and b.index not in row_slot_blocks and not b.is_dynamic
    ]
    if not protected:
        return []
    generated_tables = {
        (b.row_count, b.column_count, b.text_sha256) for b in generated.blocks if b.kind == "table"
    }
    issues: list[FidelityIssue] = []
    for block in protected:
        key = (block.row_count, block.column_count, block.text_sha256)
        if key not in generated_tables:
            issues.append(
                FidelityIssue(
                    code=TEMPLATE_TABLE,
                    severity=BLOCKING,
                    message=(
                        f"Protected table at block {block.index} "
                        f"({block.row_count}x{block.column_count}) does not survive binding "
                        "unchanged."
                    ),
                    details={"block_index": block.index},
                )
            )
    return issues


# --------------------------------------------------------------------------- entry point


def compare(
    template: TemplateManifest,
    generated: TemplateManifest,
    *,
    template_pages: int | None = None,
    generated_pages: int | None = None,
) -> FidelityReport:
    """Compare a template manifest against the manifest of a bound document."""
    expected_blocks, preserved_blocks, issues = _check_blocks(template, generated)

    headers_changed, header_issues = _compare_parts(
        "Header", TEMPLATE_HEADER_FOOTER, template.headers, generated.headers
    )
    footers_changed, footer_issues = _compare_parts(
        "Footer", TEMPLATE_HEADER_FOOTER, template.footers, generated.footers
    )
    styles_changed, style_issues = _compare_parts(
        "Style", TEMPLATE_STYLES, template.styles, generated.styles
    )
    numbering_changed, numbering_issues = _compare_parts(
        "Numbering", TEMPLATE_STYLES, template.numbering, generated.numbering
    )
    page_setup_changed, page_issues = _check_page_setup(template, generated)

    issues.extend(header_issues)
    issues.extend(footer_issues)
    issues.extend(style_issues)
    issues.extend(numbering_issues)
    issues.extend(page_issues)
    issues.extend(_check_tables(template, generated))

    if (
        template_pages is not None
        and generated_pages is not None
        and template_pages != generated_pages
    ):
        issues.append(
            FidelityIssue(
                code=TEMPLATE_PAGINATION,
                severity=WARNING,
                message=(
                    f"Generated document paginates to {generated_pages} page(s); the reference "
                    f"renders {template_pages}."
                ),
                details={"expected": template_pages, "actual": generated_pages},
            )
        )

    return FidelityReport(
        template_hash=template.fingerprint.sha256,
        required_blocks_expected=expected_blocks,
        required_blocks_preserved=preserved_blocks,
        styles_changed=styles_changed,
        headers_changed=headers_changed,
        footers_changed=footers_changed,
        numbering_changed=numbering_changed,
        page_setup_changed=page_setup_changed,
        issues=tuple(issues),
    )


def verify(
    template_bytes: bytes,
    generated_bytes: bytes,
    manifest: TemplateManifest | None = None,
) -> FidelityReport:
    """Analyze both documents and compare them. The convenience entry point."""
    template_manifest = manifest or analyze(template_bytes)
    return compare(template_manifest, analyze(generated_bytes))

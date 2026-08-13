"""Writes generated content into a clone of the attorney's own template.

The document is never rebuilt. The original ``.docx`` is opened, only the
elements a :class:`DynamicSlot` points at are edited, and the file is saved
again — so styles, numbering, headers, footers, section properties, embedded
images and every untouched paragraph keep the exact XML they arrived with.

Two rules make that hold:

* a slot is edited **in place**, reusing the run properties already on the
  element, so replacement text inherits the template's font, size and weight;
* a block or row slot clones its own source element for each output item, so
  repeated content is formatted identically to the sample the attorney wrote.

An unbound slot is an error, not an empty string. Silently shipping ``{{...}}``
in a demand letter, or silently shipping nothing where a figure belongs, are
both worse than refusing to render.
"""

from __future__ import annotations

import copy
import io
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from docx import Document
from docx.oxml.ns import qn

from .analyzer import PLACEHOLDER_RE
from .manifest import DynamicSlot, SlotKind, TemplateManifest

#: What a slot may be bound to, by kind.
InlineValue = str
BlockValue = Sequence[str]
RowValue = Sequence[Mapping[str, str]]
SlotValue = InlineValue | BlockValue | RowValue


class SlotBindingError(ValueError):
    """A slot could not be bound to a value."""


class UnboundSlotError(SlotBindingError):
    """The template declares a slot that generation supplied no value for."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = list(names)
        super().__init__(
            "template slots have no generated value: " + ", ".join(sorted(self.names))
        )


@dataclass(frozen=True)
class BindReport:
    """What binding actually did — recorded on the demand for the audit trail."""

    template_sha256: str
    bound_slots: tuple[str, ...] = ()
    inline_replacements: int = 0
    block_paragraphs: int = 0
    table_rows: int = 0
    skipped_slots: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "template_sha256": self.template_sha256,
            "bound_slots": list(self.bound_slots),
            "inline_replacements": self.inline_replacements,
            "block_paragraphs": self.block_paragraphs,
            "table_rows": self.table_rows,
            "skipped_slots": list(self.skipped_slots),
        }


@dataclass
class _Counters:
    inline: int = 0
    blocks: int = 0
    rows: int = 0
    bound: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- text nodes


def _text_nodes(element) -> list:
    return list(element.iter(qn("w:t")))


def _set_node_text(node, text: str) -> None:
    node.text = text
    # Word drops leading/trailing whitespace unless the part says otherwise.
    node.set(qn("xml:space"), "preserve")


def _replace_inline(paragraph_element, values: Mapping[str, str]) -> int:
    """Replace ``{{name}}`` runs of text without disturbing run formatting.

    Word routinely splits a placeholder across several runs (spell-check state,
    tracked formatting). The replacement is written into the run that holds the
    start of the match and the remaining characters are removed from the runs
    that follow, so the substituted text carries the first run's properties.
    """
    nodes = _text_nodes(paragraph_element)
    if not nodes:
        return 0
    texts = [node.text or "" for node in nodes]
    full = "".join(texts)

    matches = [m for m in PLACEHOLDER_RE.finditer(full) if m.group(1) in values]
    if not matches:
        return 0

    # Offsets are computed against ``full``; editing right to left keeps them valid.
    starts: list[int] = []
    offset = 0
    for text in texts:
        starts.append(offset)
        offset += len(text)

    for match in reversed(matches):
        replacement = values[match.group(1)]
        begin, end = match.start(), match.end()
        for node_index in range(len(nodes) - 1, -1, -1):
            node_start = starts[node_index]
            node_end = node_start + len(texts[node_index])
            if node_end <= begin or node_start >= end:
                continue
            local_begin = max(begin - node_start, 0)
            local_end = min(end - node_start, len(texts[node_index]))
            head = texts[node_index][:local_begin]
            tail = texts[node_index][local_end:]
            # The run holding the start of the match receives the replacement;
            # the others simply lose their share of the placeholder.
            insert = replacement if node_start <= begin < node_end else ""
            texts[node_index] = head + insert + tail

    for node, text in zip(nodes, texts):
        _set_node_text(node, text)
    return len(matches)


def _paragraph_runs(paragraph_element) -> list:
    return paragraph_element.findall(qn("w:r"))


def _write_paragraph_text(paragraph_element, text: str) -> None:
    """Put ``text`` into a paragraph, keeping its first run's formatting.

    A newline inside ``text`` becomes a real ``w:br``. Left as a literal ``\\n``
    inside a ``w:t`` Word renders nothing at all, which silently collapses a
    bulleted or numbered block into one unreadable line.
    """
    runs = _paragraph_runs(paragraph_element)
    if not runs:
        run = paragraph_element.makeelement(qn("w:r"), {})
        paragraph_element.append(run)
        runs = [run]

    keeper = runs[0]
    for extra in runs[1:]:
        paragraph_element.remove(extra)

    # Keep the run's properties; discard everything it used to contain.
    for child in list(keeper):
        if child.tag != qn("w:rPr"):
            keeper.remove(child)

    for index, line in enumerate(text.split("\n")):
        if index:
            keeper.append(keeper.makeelement(qn("w:br"), {}))
        node = keeper.makeelement(qn("w:t"), {})
        _set_node_text(node, line)
        keeper.append(node)


def _replace_block(paragraph_element, paragraphs: Sequence[str]) -> int:
    """Swap one placeholder paragraph for N paragraphs cloned from it."""
    parent = paragraph_element.getparent()
    body = list(paragraphs) or [""]
    anchor = paragraph_element
    written = 0
    for text in body:
        clone = copy.deepcopy(paragraph_element)
        _write_paragraph_text(clone, text)
        anchor.addnext(clone)
        anchor = clone
        written += 1
    parent.remove(paragraph_element)
    return written


def _replace_rows(table_element, row_index: int, collection: str, items: RowValue) -> int:
    """Clone a sample row once per item, then drop the sample."""
    rows = table_element.findall(qn("w:tr"))
    if row_index >= len(rows):
        raise SlotBindingError(
            f"row slot {collection!r} points at row {row_index} of a table with {len(rows)} rows"
        )
    template_row = rows[row_index]
    anchor = template_row
    written = 0
    for item in items:
        clone = copy.deepcopy(template_row)
        values = {f"{collection}[].{key}": str(value) for key, value in item.items()}
        for cell in clone.findall(qn("w:tc")):
            for paragraph in cell.findall(qn("w:p")):
                _replace_inline(paragraph, values)
        anchor.addnext(clone)
        anchor = clone
        written += 1
    table_element.remove(template_row)
    return written


# --------------------------------------------------------------------------- bind


def _validate_values(
    manifest: TemplateManifest,
    values: Mapping[str, SlotValue],
    allow_missing: Sequence[str],
) -> list[str]:
    permitted = set(allow_missing)
    missing = [
        slot.name
        for slot in manifest.slots
        if slot.name not in values and slot.name not in permitted
    ]
    if missing:
        raise UnboundSlotError(sorted(set(missing)))
    unknown = sorted(set(values) - set(manifest.slot_names()))
    return unknown


def _coerce_inline(name: str, value: SlotValue) -> str:
    if isinstance(value, str):
        return value
    raise SlotBindingError(f"inline slot {name!r} needs a string, got {type(value).__name__}")


def _coerce_block(name: str, value: SlotValue) -> Sequence[str]:
    if isinstance(value, str):
        return value.split("\n\n") if value.strip() else [""]
    if isinstance(value, Sequence):
        return [str(part) for part in value]
    raise SlotBindingError(f"block slot {name!r} needs a string or list of strings")


def _coerce_rows(name: str, value: SlotValue) -> RowValue:
    if isinstance(value, Sequence) and not isinstance(value, str):
        for item in value:
            if not isinstance(item, Mapping):
                raise SlotBindingError(f"row slot {name!r} needs a list of mappings")
        return list(value)  # type: ignore[arg-type]
    raise SlotBindingError(f"row slot {name!r} needs a list of mappings")


def bind(
    template_bytes: bytes,
    manifest: TemplateManifest,
    values: Mapping[str, SlotValue],
    *,
    allow_missing: Sequence[str] = (),
) -> tuple[bytes, BindReport]:
    """Return ``(docx_bytes, report)`` for the template with ``values`` bound in."""
    skipped = _validate_values(manifest, values, allow_missing)
    document = Document(io.BytesIO(template_bytes))
    counters = _Counters()

    body_children = [
        child
        for child in document.element.body.iterchildren()
        if child.tag in (qn("w:p"), qn("w:tbl"))
    ]

    # Right to left: a BLOCK slot changes how many elements precede it, so
    # editing from the end keeps every earlier block_index valid.
    for slot in sorted(manifest.slots, key=lambda s: s.block_index, reverse=True):
        if slot.name not in values:
            continue
        if slot.block_index >= len(body_children):
            raise SlotBindingError(
                f"slot {slot.name!r} points at block {slot.block_index}, "
                f"but the template body has {len(body_children)} blocks"
            )
        element = body_children[slot.block_index]
        value = values[slot.name]

        if slot.kind == SlotKind.INLINE:
            text = _coerce_inline(slot.name, value)
            if element.tag == qn("w:tbl"):
                replaced = sum(
                    _replace_inline(paragraph, {slot.name: text})
                    for paragraph in element.iter(qn("w:p"))
                )
            else:
                replaced = _replace_inline(element, {slot.name: text})
            counters.inline += replaced
        elif slot.kind == SlotKind.BLOCK:
            counters.blocks += _replace_block(element, _coerce_block(slot.name, value))
        elif slot.kind == SlotKind.ROW:
            if element.tag != qn("w:tbl"):
                raise SlotBindingError(f"row slot {slot.name!r} is not on a table")
            counters.rows += _replace_rows(
                element, slot.row_index or 0, slot.name, _coerce_rows(slot.name, value)
            )
        counters.bound.append(slot.name)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue(), BindReport(
        template_sha256=manifest.fingerprint.sha256,
        bound_slots=tuple(sorted(set(counters.bound))),
        inline_replacements=counters.inline,
        block_paragraphs=counters.blocks,
        table_rows=counters.rows,
        skipped_slots=tuple(skipped),
    )


def unbound_placeholders(data: bytes) -> list[str]:
    """Placeholders still present in a rendered document. Should always be empty."""
    document = Document(io.BytesIO(data))
    found: list[str] = []
    for paragraph in document.element.body.iter(qn("w:p")):
        text = "".join(node.text or "" for node in paragraph.iter(qn("w:t")))
        found.extend(PLACEHOLDER_RE.findall(text))
    return sorted(set(found))


def slot_targets(manifest: TemplateManifest) -> dict[str, DynamicSlot]:
    """Slot name -> slot, for callers building a value mapping."""
    return {slot.name: slot for slot in manifest.slots}

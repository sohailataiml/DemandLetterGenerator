"""Typed description of an attorney's Word template.

The manifest is what lets the system bind generated content into a real
template without rebuilding it. It records where every block lives, which of
those blocks are allowed to change, and a fingerprint of everything that is
not.

Nothing here mutates a document. The manifest is a read-only description
produced by :mod:`analyzer`, consumed by :mod:`binder` and :mod:`fidelity`, and
persisted as JSON alongside the uploaded template.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SlotKind(str, Enum):
    """How a dynamic region is bound.

    ``INLINE``  a placeholder inside a paragraph's text; only the placeholder
                characters are replaced, the run's formatting is kept.
    ``BLOCK``   a paragraph whose entire text is one placeholder; it is replaced
                by N paragraphs cloned from it, so spacing and style survive.
    ``ROW``     a table row containing ``{{collection[].field}}`` placeholders;
                the row is cloned per item, preserving borders and widths.
    """

    INLINE = "inline"
    BLOCK = "block"
    ROW = "row"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class TemplateFingerprint:
    """Identifies both the exact bytes and the structure they encode."""

    sha256: str
    structure_sha256: str
    byte_size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateFingerprint:
        return cls(
            sha256=data["sha256"],
            structure_sha256=data["structure_sha256"],
            byte_size=int(data["byte_size"]),
        )


@dataclass(frozen=True)
class TemplateBlock:
    """One top-level body element: a paragraph or a table."""

    index: int
    kind: str  # "paragraph" | "table"
    style: str | None
    text: str
    text_sha256: str
    outline_level: int | None = None
    numbering_id: str | None = None
    has_page_break: bool = False
    row_count: int = 0
    column_count: int = 0
    is_dynamic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateBlock:
        return cls(**data)


@dataclass(frozen=True)
class TemplateSection:
    """A heading and the blocks that belong to it.

    ``key`` is a slug derived from the heading text, which is what lets a
    generated narrative section be matched to the place in the template it
    belongs.
    """

    key: str
    title: str
    heading_index: int | None
    start_index: int
    end_index: int  # exclusive

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateSection:
        return cls(**data)


@dataclass(frozen=True)
class DynamicSlot:
    """A region the binder is permitted to write into. Nothing else is."""

    name: str
    kind: SlotKind
    block_index: int
    placeholder: str | None = None
    section_key: str | None = None
    fields: tuple[str, ...] = ()
    table_index: int | None = None
    row_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["fields"] = list(self.fields)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DynamicSlot:
        payload = dict(data)
        payload["kind"] = SlotKind(payload["kind"])
        payload["fields"] = tuple(payload.get("fields") or ())
        return cls(**payload)


@dataclass(frozen=True)
class PageSetup:
    """Section properties that decide how the page physically looks."""

    page_width: int | None = None
    page_height: int | None = None
    orientation: str | None = None
    margin_top: int | None = None
    margin_bottom: int | None = None
    margin_left: int | None = None
    margin_right: int | None = None
    header_distance: int | None = None
    footer_distance: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageSetup:
        return cls(**data)


@dataclass(frozen=True)
class PartDigest:
    """A package part reduced to its name and a hash of its canonical XML."""

    name: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PartDigest:
        return cls(**data)


@dataclass(frozen=True)
class TemplateManifest:
    """Everything the pipeline knows about one uploaded template."""

    fingerprint: TemplateFingerprint
    blocks: tuple[TemplateBlock, ...] = ()
    sections: tuple[TemplateSection, ...] = ()
    slots: tuple[DynamicSlot, ...] = ()
    headers: tuple[PartDigest, ...] = ()
    footers: tuple[PartDigest, ...] = ()
    styles: tuple[PartDigest, ...] = ()
    numbering: tuple[PartDigest, ...] = ()
    page_setup: PageSetup = field(default_factory=PageSetup)
    section_break_count: int = 0
    image_parts: tuple[str, ...] = ()
    analyzer_version: str = "template_analyzer_v1"

    # ------------------------------------------------------------------ lookup

    @property
    def required_block_count(self) -> int:
        """Blocks that must survive binding untouched."""
        return sum(1 for block in self.blocks if not block.is_dynamic)

    def slot(self, name: str) -> DynamicSlot | None:
        return next((s for s in self.slots if s.name == name), None)

    def slot_names(self) -> tuple[str, ...]:
        return tuple(slot.name for slot in self.slots)

    def section(self, key: str) -> TemplateSection | None:
        return next((s for s in self.sections if s.key == key), None)

    def immutable_block_indexes(self) -> frozenset[int]:
        dynamic = {slot.block_index for slot in self.slots}
        return frozenset(b.index for b in self.blocks if b.index not in dynamic)

    # --------------------------------------------------------- serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer_version": self.analyzer_version,
            "fingerprint": self.fingerprint.to_dict(),
            "blocks": [b.to_dict() for b in self.blocks],
            "sections": [s.to_dict() for s in self.sections],
            "slots": [s.to_dict() for s in self.slots],
            "headers": [p.to_dict() for p in self.headers],
            "footers": [p.to_dict() for p in self.footers],
            "styles": [p.to_dict() for p in self.styles],
            "numbering": [p.to_dict() for p in self.numbering],
            "page_setup": self.page_setup.to_dict(),
            "section_break_count": self.section_break_count,
            "image_parts": list(self.image_parts),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateManifest:
        return cls(
            analyzer_version=data.get("analyzer_version", "template_analyzer_v1"),
            fingerprint=TemplateFingerprint.from_dict(data["fingerprint"]),
            blocks=tuple(TemplateBlock.from_dict(b) for b in data.get("blocks", [])),
            sections=tuple(TemplateSection.from_dict(s) for s in data.get("sections", [])),
            slots=tuple(DynamicSlot.from_dict(s) for s in data.get("slots", [])),
            headers=tuple(PartDigest.from_dict(p) for p in data.get("headers", [])),
            footers=tuple(PartDigest.from_dict(p) for p in data.get("footers", [])),
            styles=tuple(PartDigest.from_dict(p) for p in data.get("styles", [])),
            numbering=tuple(PartDigest.from_dict(p) for p in data.get("numbering", [])),
            page_setup=PageSetup.from_dict(data.get("page_setup", {})),
            section_break_count=int(data.get("section_break_count", 0)),
            image_parts=tuple(data.get("image_parts", [])),
        )

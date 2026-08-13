"""Template-preserving document generation.

    attorney template.docx
        -> analyzer.analyze()  -> TemplateManifest (structure + dynamic slots)
        -> slots.build_values() -> deterministic values for each slot
        -> binder.bind()        -> a clone of the original with slots filled
        -> fidelity.verify()    -> proof that nothing else changed

The original OOXML is the substrate throughout. Nothing in this package builds
a Word document from scratch.
"""

from .analyzer import TemplateAnalysisError, analyze
from .binder import BindReport, SlotBindingError, UnboundSlotError, bind, unbound_placeholders
from .fidelity import FidelityIssue, FidelityReport, compare, verify
from .manifest import (
    DynamicSlot,
    PageSetup,
    PartDigest,
    SlotKind,
    TemplateBlock,
    TemplateFingerprint,
    TemplateManifest,
    TemplateSection,
)
from .slots import MISSING_MARKER, UnknownSlotError, build_values, known_slot_names

__all__ = [
    "BindReport",
    "DynamicSlot",
    "FidelityIssue",
    "FidelityReport",
    "MISSING_MARKER",
    "PageSetup",
    "PartDigest",
    "SlotBindingError",
    "SlotKind",
    "TemplateAnalysisError",
    "TemplateBlock",
    "TemplateFingerprint",
    "TemplateManifest",
    "TemplateSection",
    "UnboundSlotError",
    "UnknownSlotError",
    "analyze",
    "bind",
    "build_values",
    "compare",
    "known_slot_names",
    "unbound_placeholders",
    "verify",
]

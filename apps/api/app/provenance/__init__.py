"""Provenance: tying assertions back to exact passages in stored evidence."""

from .citations import (
    MIN_SIMILARITY,
    MatchKind,
    ResolvedCitation,
    resolve,
    text_hash,
    verify_offsets,
)

__all__ = [
    "MIN_SIMILARITY",
    "MatchKind",
    "ResolvedCitation",
    "resolve",
    "text_hash",
    "verify_offsets",
]

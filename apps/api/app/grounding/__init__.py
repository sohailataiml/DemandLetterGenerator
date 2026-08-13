"""Semantic claim grounding.

    generated section
        -> claims.segment()        atomic factual claims, with offsets
        -> checker.check_claim()   graded against the VERIFIED fact store
        -> SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED

The grading is deterministic. A model may propose how to split prose into
claims; it never decides whether one is true.
"""

from .checker import (
    PARTIAL_THRESHOLD,
    SUPPORT_THRESHOLD,
    ClaimVerdict,
    GroundingContext,
    check_claim,
    content_tokens,
)
from .claims import Claim, segment, verify_segmentation
from .service import (
    CLAIM_CONTRADICTS,
    CLAIM_PROPOSED_ONLY,
    CLAIM_SUPERSEDED,
    CLAIM_UNSUPPORTED,
    GradedClaim,
    GroundingReport,
    evaluate,
    persist,
    stale_reliance,
)

__all__ = [
    "CLAIM_CONTRADICTS",
    "CLAIM_PROPOSED_ONLY",
    "CLAIM_SUPERSEDED",
    "CLAIM_UNSUPPORTED",
    "PARTIAL_THRESHOLD",
    "SUPPORT_THRESHOLD",
    "Claim",
    "ClaimVerdict",
    "GradedClaim",
    "GroundingContext",
    "GroundingReport",
    "check_claim",
    "content_tokens",
    "evaluate",
    "persist",
    "segment",
    "stale_reliance",
    "verify_segmentation",
]

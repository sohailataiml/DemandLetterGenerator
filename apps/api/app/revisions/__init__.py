"""Attorney-directed AI revisions, as proposals rather than edits.

    instruction
        -> provider.revise()        bounded replacement text
        -> constraints.check()      deterministic envelope check
        -> RevisionProposal         persisted, inert, with a diff
        -> attorney accepts         the only path that changes the document

Creating a proposal never changes a demand. That is INVARIANT-008.
"""

from .constraints import (
    ConstraintViolation,
    RevisionConstraint,
    check,
    check_freshness,
    text_hash,
)
from .provider import (
    RevisionDraft,
    RevisionError,
    RevisionProvider,
    RevisionRequest,
    RhetoricalStubProvider,
    get_revision_provider,
)
from .service import (
    ProposalView,
    RevisionStateError,
    accept,
    list_proposals,
    propose,
    reject,
    unified_diff,
    view,
)

__all__ = [
    "ConstraintViolation",
    "ProposalView",
    "RevisionConstraint",
    "RevisionDraft",
    "RevisionError",
    "RevisionProvider",
    "RevisionRequest",
    "RevisionStateError",
    "RhetoricalStubProvider",
    "accept",
    "check",
    "check_freshness",
    "get_revision_provider",
    "list_proposals",
    "propose",
    "reject",
    "text_hash",
    "unified_diff",
    "view",
]

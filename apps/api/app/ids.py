"""Prefixed, opaque identifiers.

Prefixes make IDs self-describing in audit logs and API responses, which matters
when reconstructing how a document was produced months later.
"""

from __future__ import annotations

import uuid
from functools import partial

CASE = "case"
PARTY = "pty"
ROLE = "role"
CLAIM = "clm"
CARRIER = "carr"
ACCIDENT = "acc"
VEHICLE = "veh"
PROVIDER = "prv"
TREATMENT = "evt"
DIAGNOSIS = "dx"
IMAGING = "img"
BILL = "bill"
FUTURE = "fut"
DAMAGE = "dmg"
SETTLEMENT = "stl"
DOCUMENT = "doc"
PAGE = "page"
FACT = "fact"
FACT_SOURCE = "fsrc"
DEMAND = "dmnd"
SECTION = "sec"
ISSUE = "vis"
AUDIT = "aud"
USER = "user"
TEMPLATE = "tpl"
CITATION = "cite"
CLAIM_CHECK = "clmchk"
REVISION = "rev"
REVISION_OP = "revop"
JOB = "job"
EXTRACTION = "extr"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def id_factory(prefix: str):
    """Return a zero-arg callable suitable for a SQLAlchemy column default."""
    return partial(new_id, prefix)

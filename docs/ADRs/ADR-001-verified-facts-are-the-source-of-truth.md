# ADR-001 — Verified facts are the source of truth

**Status:** accepted

## Context

A demand letter is a legal assertion. Every sentence in it is something the firm
is prepared to defend. Documents, records and bills arrive in bulk and are
messy; models read them well but confidently. Somewhere between "a PDF said
something" and "the letter asserts it" a human has to take responsibility.

## Decision

The `facts` table is the only authoritative statement of what the case says. A
fact moves `PROPOSED → VERIFIED` only through an authenticated human action, and
only with at least one document citation. `generation/context.py` loads
`VERIFIED` facts and nothing else, so no code path downstream can reach an
unverified one — it is a query constraint, not a policy.

## Consequences

- Generation on a case with no verified facts produces sections that say so and
  block approval (`NARRATIVE_002`), rather than a plausible empty letter.
- The bottleneck is human review. That is the intended cost.
- `SOURCE_001`, `SOURCE_002` and `CLAIM_002` catch a section that cites
  something not currently verified, including via direct database tampering.

## Rejected

**A confidence threshold that auto-verifies above some score.** It converts a
model's self-assessment into legal authority, which is exactly the transfer this
system exists to prevent. Confidence is recorded and shown; it gates nothing.

# ADR-004 — AI revisions are patches, not rewrites

**Status:** accepted

## Context

Attorneys need to refine a draft in their own words: "make the liability section
more forceful", "shorten this". The obvious implementation regenerates the
section and swaps it in. That has two problems. The attorney cannot see what
changed, and "more forceful" is an invitation to add claims — a stronger
sentence is easy to write if you are allowed to assert more.

## Decision

A revision is a **proposal**: replacement text, a set of constraints, a
deterministic check of the text against those constraints, and a unified diff.
`propose()` writes a proposal row and changes nothing about the demand.
`accept()` is a separate call that requires an attorney, re-checks the section
hash for staleness, re-runs the constraints, and only then writes.

Constraints are enforced in code, not in the prompt: amounts and dates must be
unchanged, no entity may be named that was not already named, required literals
must survive, and the text may not balloon.

## Consequences

- INVARIANT-008 is structural. There is no code path from "the model produced
  text" to "the document changed".
- Accepting one proposal supersedes other open proposals for that section, so
  two edits written against the same text cannot both apply.
- The audit trail distinguishes an AI-originated change (`origin: ai_revision`,
  `applied: true`) from a human edit, permanently.
- An offline stub can only adjust emphasis, and says so when an instruction is
  beyond it rather than inventing something.

## Rejected

**Trusting the prompt's constraint list.** A constraint that lives only in a
prompt is a wish. The same list is sent to the model *and* checked afterwards.

# ADR-009 — A citation never claims more precision than it has

**Status:** accepted

## Context

Provenance ends at a rectangle on a page. An attorney clicks a sentence in a
demand, and the original medical record opens at the right page with the quoted
passage highlighted — that is the feature, and it is the moment the system is
most persuasive.

Which is exactly why it is the moment it can do the most damage. A highlight
drawn over the wrong paragraph is not a rendering bug; it is the software
vouching for a sentence the record does not contain, in front of an adjuster, in
a document the firm signs. Precision that is displayed is precision that is
relied on.

Four kinds of certainty are involved, and they are not the same:

```
document-level  ≠  page-level  ≠  span-level  ≠  box-level
```

A system that stores one confidence field, or that renders every citation the
same way, has already collapsed them.

## Decision

**Each level of precision is recorded separately, and the strongest one a
citation reaches is stored explicitly as `citation_status`.** Nothing is
inferred from which fields happen to be populated.

- `EXACT` — the passage occurs once on the page, verbatim up to whitespace.
  Offsets are real. Bounding boxes are stored too, if the page has geometry.
- `AMBIGUOUS` — the page contains the passage more than once. No offsets, no
  boxes; a reviewer settles it.
- `TEXT_ONLY` — a paraphrase, aligned approximately. Offsets are kept so the
  reviewer can be taken to the right part of the page. **Never a rectangle.**
- `UNRESOLVED` — no quote, or one the page does not contain. Document and page,
  and nothing finer.

Three rules follow, and each is enforced in code rather than asserted in a
comment:

1. **Geometry is verified before it is stored.** `boxes_for_span()` re-reads the
   words it selected and compares them with the text the offsets select. A
   mismatch returns no boxes at all. A wrong highlight is therefore not a bug
   waiting to be found; it is a state the writer cannot reach.
2. **Ambiguity is never resolved silently.** Taking the first of several matches
   is a coin flip presented as a fact. `POST /v1/citations/{id}/resolve` accepts
   a human's choice — and only a selection that is an occurrence of the passage
   already quoted, so provenance can be sharpened but not redirected.
3. **Enrichment is not editing.** Adding geometry to an existing citation writes
   citation columns only. A `VERIFIED` fact's value, summary, status, reviewer
   and timestamps are untouched, which is what makes the backfill safe to run
   over approved work.

## Consequences

- The evidence viewer has four distinct states and says which one it is in.
  "Exact source highlight unavailable. Supporting page shown instead." is a
  first-class outcome, not an error.
- Old citations, scanned pages and plain-text sources degrade gracefully:
  page-level provenance is thin, but it is honest, and it still verifies facts.
- The backfill improves what it can prove and leaves the rest alone, reporting
  counts per outcome rather than a single success number.

## Rejected

**Deriving a box from the best fuzzy match.** It would have given nearly every
citation a highlight, and the failures would have been invisible: a rectangle
over roughly-the-right-paragraph looks exactly like a rectangle over the right
one. The value of the highlight comes entirely from it being trustworthy.

**Rendering pages to images server-side and overlaying on those.** Simpler to
align, but it puts a second, derived copy of somebody's medical record on disk
and makes the viewer show a picture of the evidence rather than the evidence.
The original PDF is rendered in the browser instead, unaltered.

**A single numeric confidence.** One float cannot distinguish "we know the page
but not the passage" from "we know the passage but the page has no layout", and
every consumer would have invented its own thresholds for what to draw.

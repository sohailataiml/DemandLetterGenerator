# ADR-008 — Claim grounding is deterministic, not model-judged

**Status:** accepted

## Context

Literal guards catch a wrong number or an unsupported date. They do not catch
"the collision caused permanent nerve damage" written from a record that says
"disc extrusion with nerve root contact" — every word is defensible, and the
sentence is not.

The obvious fix is to ask a model whether the text is hallucinated. A model
grading its own output grades it generously, and a second model has no more
access to the evidence than the first: both are guessing from the same text.

## Decision

Grading is arithmetic over the verified fact store.

- **Coverage** — what share of a claim's content words appear in the facts its
  section cites, plus the literals the deterministic layer produced.
- **Escalation** — permanence, causation, prognosis and degree terms must appear
  *in the evidence*, not merely be surrounded by words that do.
- **Contradiction** — a claim that negates a phrase the evidence states plainly
  is `UNSUPPORTED` regardless of how well it scores on coverage.

A model may propose how to split prose into atomic claims. That decomposition is
verified against the source text, and a decomposition containing a sentence the
section never said is discarded in favour of deterministic segmentation.

## Consequences

- The result is reproducible and explainable: a blocked claim comes with a
  score, the facts considered, and a reason.
- Only machine-drafted sections are graded. Attorney-authored text is the
  attorney's own assertion; literal guards still apply to it.

## Limits, stated rather than hidden

- Coverage is **lexical**. A paraphrase using entirely different vocabulary
  scores low and is flagged for review rather than silently accepted — the safe
  direction to be wrong in, but it does mean false positives on good writing.
- Contradiction detection is narrow and does not claim to be entailment.
- A sentence carrying two assertions is graded as one claim.

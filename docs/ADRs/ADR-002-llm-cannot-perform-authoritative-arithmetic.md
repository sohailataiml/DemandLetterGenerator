# ADR-002 — The LLM cannot perform authoritative arithmetic

**Status:** accepted

## Context

Demand letters are arithmetic wrapped in prose: bills totalled, ranges summed,
policy limits compared. Language models do arithmetic plausibly and wrongly, and
a wrong total in a demand letter is a malpractice question, not a typo.

## Decision

`app/damages/calculator.py` is the only source of monetary totals, using
`Decimal` end to end. Money crosses the wire as a **string** so no float appears
on either side. The drafting prompt states that totals are inserted separately
and must not be restated; `NARRATIVE_001` then rejects any dollar amount in
generated prose that is not in the structured case data, and `MONEY_001` checks
the printed total against the calculator's sum.

## Consequences

- The letter can state a figure the model never saw.
- A model that invents "$750,000" blocks approval rather than reaching a reader.
- Template slots like `{{medical_expenses_total}}` resolve through the
  calculator, so even a template asking for a figure gets a computed one.

## Rejected

**Letting the model restate a total we hand it.** Restating is a copy, and a
copy can be mistyped. Passing the figure through a slot is the same effort and
cannot drift.

# ADR-005 — AI extraction produces PROPOSED facts only

**Status:** accepted

## Context

Extraction is where the volume is: a case is hundreds of pages, and reading them
by hand is the work the system is supposed to remove. It is also where a model
is most useful and most dangerous — a plausible misreading of a record becomes a
fact nobody notices.

## Decision

`extraction/service.py` can create facts in exactly one status: `PROPOSED`.
There is no parameter, no flag, and no provider return value that changes this.

Every candidate must carry a verbatim quote. That quote is looked up in the page
text the ingestion pipeline stored, and a candidate whose quote is not there is
**dropped and recorded as rejected**, with the reason. A model cannot cite a
document into saying something it does not say, because the citation is resolved
against the document rather than accepted from the model.

## Consequences

- Extraction volume becomes review volume. The UI has to make review fast; that
  is the right place for the effort.
- The rejection list is part of the audit payload, so a provider that quotes
  badly is visible rather than silently unproductive.
- The offline pattern extractor is genuinely useful and structurally incapable
  of inventing a quote, which makes it a fair adversarial baseline.

## Rejected

**Auto-verifying high-confidence extractions of "objective" fields** such as
dates and dollar amounts. Those are precisely the fields where an error is most
expensive, and confidence is the model's opinion of itself.

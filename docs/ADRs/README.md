# Architecture Decision Records

One file per decision that would be expensive to reverse, or that a reader
would otherwise assume was arbitrary.

| ADR | Decision |
| --- | --- |
| [001](ADR-001-verified-facts-are-the-source-of-truth.md) | Verified facts are the source of truth |
| [002](ADR-002-llm-cannot-perform-authoritative-arithmetic.md) | The LLM cannot perform authoritative arithmetic |
| [003](ADR-003-original-docx-is-preserved.md) | The original DOCX is preserved, not reconstructed |
| [004](ADR-004-ai-revisions-are-patches.md) | AI revisions are patches, not rewrites |
| [005](ADR-005-ai-extraction-produces-proposed-facts-only.md) | AI extraction produces PROPOSED facts only |
| [006](ADR-006-expensive-workflows-run-asynchronously.md) | Expensive workflows run asynchronously |
| [007](ADR-007-uploaded-content-is-untrusted.md) | Uploaded content is untrusted data |
| [008](ADR-008-claim-grounding-is-deterministic.md) | Claim grounding is deterministic, not model-judged |
| [009](ADR-009-a-citation-never-claims-more-precision-than-it-has.md) | A citation never claims more precision than it has |

Format: context, decision, consequences, and — where it matters — what was
rejected and why.

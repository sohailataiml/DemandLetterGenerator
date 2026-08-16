# ADR-010 — External model calls cross a privacy boundary, and fail closed

**Status:** accepted

## Context

Drafting a demand letter means sending a model the most sensitive material a
firm holds: a claimant's name, their injuries, their treatment history, their
providers, their claim number. Until now that went straight to a model vendor
over the vendor's own SDK. The prompt was well-grounded and the output was
graded, but nothing stood between the client's medical history and a third
party's servers.

A Secure AI Gateway is deployed and does exactly that job: detect sensitive
entities, apply the tenant's policy, tokenize or redact or pseudonymize, scan
the outbound payload, call the provider, and restore authorized values before
answering. It rate-limits per principal and caps ordinary request bodies at
256 KB.

## Decision

**External model calls leave through the gateway, and the application fails
closed when it cannot.**

- `DLG_LLM_PROVIDER=secure_gateway` is the preferred external path for drafting
  and revisions; `DLG_EXTRACTION_PROVIDER=secure_gateway` for extraction, which
  carries the most sensitive payload of all.
- `stub`/`pattern` remain the offline defaults, so the test suite needs no key
  and no network.
- `anthropic` is retained, explicitly documented as bypassing the gateway, and
  **never selected automatically**.
- **FastAPI is the only caller.** The gateway credential lives in this process:
  the browser never holds it, never sees it, and never calls the gateway. That
  makes the gateway's CORS policy irrelevant to this application rather than an
  obstacle to work around.
- Failure is final. An unreachable, rate-limited, or refusing gateway means the
  section is not drafted, the existing text is untouched, and nothing is marked
  generated or approved.

## Consequences

- Drafting depends on a third service being up. That is the cost of the
  boundary, and it is paid visibly: the reviewer gets a specific message and an
  unchanged document rather than a silent downgrade.
- Sensitive-data handling is centralized in something that specializes in it,
  instead of being re-implemented here. This repository stores only the
  gateway's `PrivacySummary` counts, because counts are the only privacy detail
  the gateway emits.
- Privacy and provenance stay separate controls. Neither implies the other, and
  the UI presents them separately: the gateway governs what leaves; provenance
  governs what a claim rests on.

## Rejected

**Falling back to the vendor when the gateway is down.** This is the decision
the whole ADR exists to make. An automatic fallback means that under exactly the
conditions nobody is watching — an outage, a rate limit, a policy refusal — the
system would route the material the boundary exists to protect straight past it.
The privacy guarantee would then hold only when it was not being tested. A
failed generation is recoverable; an unnoticed disclosure is not.

**Truncating an oversized prompt to fit the 256 KB limit.** Dropping facts to
make a request smaller silently changes what the letter is based on, and the
attorney would have no way to see which evidence was omitted. The request is
refused with a precise size instead.

**Relaying the gateway's 401 to the browser.** The attorney is authenticated
with this service; it is our credential to the gateway that failed. Passing the
status through would tell a signed-in user they are signed out and send them
looking for the wrong problem. It surfaces as 502 with an operator-facing
message.

**Duplicating detection locally before calling the gateway.** `/v1/chat` already
owns the end-to-end pipeline. A second implementation here would drift from the
policy the gateway actually enforces, and disagreement between the two would be
worse than either alone.

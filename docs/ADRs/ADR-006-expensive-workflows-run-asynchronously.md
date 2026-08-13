# ADR-006 — Expensive workflows run asynchronously

**Status:** accepted

## Context

A full generation run reads documents, calls a model several times, validates,
binds a template and renders a file. Against a real provider that is minutes,
not seconds. Holding an HTTP request open for it is a bad experience and a bad
architecture.

The assignment suggests Redis + ARQ. This repository has no Docker, no broker,
and no second process to deploy — deliberately, so a reviewer can clone and run
it.

## Decision

Jobs are a **persisted state machine** plus a **swappable runner**. The
`generation_jobs` row holds everything: status, an append-only stage list, the
result, the error. `POST /cases/{id}/generate` creates the row, hands the id to
the runner, and returns `202`. `GET /jobs/{id}/events` streams stage transitions
as server-sent events by reading that row.

The default runner executes the pipeline on a worker thread of the API process.
The pipeline is synchronous SQLAlchemy, so it runs on a thread rather than on
the event loop — putting it on the loop would block every other request for the
duration, which is the problem this exists to solve.

## Consequences

- Enqueueing is a single insert; the test suite asserts it stays well under the
  5-second budget.
- The pipeline calls the same services the synchronous endpoints call, so there
  is no second implementation to drift.
- **The limit, stated plainly:** a job is bound to the process that accepted it.
  With more than one API worker, an SSE stream that lands on another worker
  still reports correctly (it reads the row) but less promptly. A multi-process
  deployment implements `JobRunner` against a real queue; nothing else changes.

## Rejected

**Shipping an untested ARQ integration.** It would add Redis to the setup
instructions for a code path with no test coverage and no way to demonstrate it
working. An honest in-process runner with its limits documented is worth more
than a production-shaped one nobody has run.

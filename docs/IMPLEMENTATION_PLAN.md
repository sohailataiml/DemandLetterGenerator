# Implementation Plan

This document records where the repository stood before this body of work, where
it is going, and the invariants that any change must not break.

## Trust principle

> **Evidence determines facts. Deterministic code determines calculations and
> document structure. AI determines only prose.**

Every phase below is judged against that sentence. A change that makes the model
responsible for a number, a status transition, or a piece of document structure
is a regression regardless of how much nicer the output looks.

---

## Phase 0 — Baseline

Recorded on a clean `main` at commit `e4e467e`.

### Test baseline

| Suite | Command | Baseline | After this work |
| --- | --- | --- | --- |
| Backend | `python -m pytest` | **61 passed**, 0 failed | **293 passed**, 0 failed |
| Frontend | `cd apps/web && npm test` | **66 passed**, 0 failed | **91 passed**, 0 failed |

No failing tests at baseline, and none now. Python 3.14.4, Node 18+.

(The README previously claimed 50 frontend tests; the measured baseline was 66.)

### Current architecture

```
Next.js (apps/web, :3000)
   |  typed fetch client, TanStack Query, X-User-Id / X-User-Role headers
FastAPI (apps/api, :8000)
   |
SQLite (var/demand.db) + local filesystem object store (var/storage)
   |
Stub drafter (default) or Anthropic provider
```

Backend packages:

| Package | Responsibility |
| --- | --- |
| `domain/` | SQLAlchemy models, enums, exact-decimal `Money`, Pydantic schemas |
| `ingestion/` | scan -> immutable content-addressed store -> text extraction -> page split -> classify |
| `facts/` | `PROPOSED -> VERIFIED / REJECTED / SUPERSEDED` lifecycle |
| `medical/` | chronological timeline built from structured records |
| `damages/` | deterministic `Decimal` money arithmetic |
| `generation/` | context builder, deterministic template, AI narrative layer |
| `validation/` | rule framework, rule set, unsupported-literal text guard |
| `documents/` | DOCX rendering, PDF conversion, approval + locking |
| `security/` | header-based RBAC (development stand-in) |
| `audit/` | append-only event trail |

### Current generation workflow

```
build_context(session, demand)          # verified facts + structured records + damages
  -> generate_narratives(ctx, provider) # AI writes 4 narrative sections only
  -> templates.render(ctx, narratives)  # 11 deterministic sections + 4 AI slots
  -> persist DemandSection rows
  -> validate_demand()                  # 15 rules; BLOCKING gates approval
  -> approve_demand()                   # server-side; re-validates, locks, hashes
  -> render_docx()                      # rebuilds a Word file from scratch
```

### Current persistence architecture

- SQLAlchemy 2.0 ORM against SQLite; `Base.metadata.create_all()` on app startup.
- Alembic is a declared dependency but no migration environment exists.
- Object storage is a filesystem `LocalObjectStore` behind an `ObjectStore`
  Protocol; originals and final artifacts are written immutably.

### Current document export architecture

`app/documents/docx_renderer.py` builds a **brand new** `docx.Document()` on
every render: it sets Calibri 11pt, one-inch margins, a generated footer, then
appends paragraphs per stored section. Nothing about an attorney's real template
survives, because no template is ever read.

This is the single largest gap against the assignment and is what Phase 1 fixes.

### Baseline gaps against the assignment

| Assignment requirement | Baseline state |
| --- | --- |
| Match a real template exactly | **Absent** — document is reconstructed from scratch |
| AI extraction into reviewable facts | **Absent** — facts are created by hand through the API |
| Span-level provenance | Page-level only; UI highlights by text matching |
| Semantic claim grounding | Regex/literal guards only |
| Attorney AI refinement | Regenerate-whole-section only; no patches, no diff |
| Async jobs + streaming progress | Synchronous request path |
| Migrations | `create_all` |
| Adversarial / prompt-injection tests | **Absent** |
| Collaboration | **Absent** (stretch goal) |

---

## Target architecture

```
Attorney template.docx
      |
      v
  Template Analyzer  ---->  Template Manifest (sections, blocks, slots,
      |                      styles, numbering, headers, footers, page setup,
      |                      fingerprint)
      v
  Clone original OOXML
      |
      v
  Bind ONLY approved dynamic regions
      |                      ^
      |                      |
      |            deterministic values (money, dates, metadata)
      |            validated prose (AI narrative, claim-grounded)
      v
  Fidelity validation (TEMPLATE_001..008)
      |
      v
  final-demand.docx
```

Around that core:

```
case materials -> parser -> chunks -> AI extraction -> PROPOSED facts
                                                          |
                                              attorney review (human)
                                                          v
                                              VERIFIED facts (immutable)
                                                          |
                       deterministic damages <------------+
                       AI narrative prose  <--------------+
                                |
                       claim grounding validation
                                |
                       template binding + fidelity
                                |
                       server-side approval gate
                                |
                       final DOCX (original template preserved)
```

---

## Phase boundaries

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Assessment, baseline, this document | done |
| 1 | Template ingestion + template-preserving DOCX generation | done |
| 2 | Fidelity validation + golden-document tests | done |
| 3 | AI extraction of case materials into PROPOSED facts | done |
| 4 | Span-aware citations / stronger provenance | done |
| 5 | Semantic claim-grounding validation | done |
| 6 | Attorney AI revision workflow using patches | done |
| 7 | Async generation jobs + SSE progress | done |
| 8 | Alembic migrations + production-ready interfaces | done |
| 9 | Prompt-injection and adversarial safety tests + quality gate | done |
| 10 | Developer experience and documentation | done |
| 11 | Frontend trust/readiness improvements | done |
| 12 | Collaborative editor (stretch) | not implemented — see README |

Each phase is additive. Nothing in the baseline generation path was deleted: a
demand with no bound template still renders through the original
`docx_renderer`, and every baseline test still passes unchanged.

---

## Invariants

These are enforced by tests under `apps/api/tests/invariants/` and
`apps/api/tests/adversarial/`. Breaking one is a defect, not a tradeoff.

```text
INVARIANT-001
An unverified fact must never become authoritative generated content.

INVARIANT-002
An approved/verified fact cannot be silently mutated.

INVARIANT-003
The LLM must never perform authoritative arithmetic.

INVARIANT-004
Pending monetary values must never be treated as zero.

INVARIANT-005
AI-generated factual prose must be traceable to verified facts/evidence.

INVARIANT-006
Template formatting/layout outside explicitly dynamic regions must not be mutated.

INVARIANT-007
Approval must remain a server-side decision.

INVARIANT-008
AI attorney revisions must be proposed changes, not silent document mutations.
```

### Where each invariant is enforced

| Invariant | Enforced by |
| --- | --- |
| 001 | `facts/service.py` lifecycle; `generation/context.py` only loads `VERIFIED`; rules `SOURCE_001`, `SOURCE_002`, `CLAIM_002` |
| 002 | `facts/service.py` has no update path; supersession creates a new revision; `PATCH /facts/{id}` does not exist |
| 003 | `damages/calculator.py` is the only arithmetic; `NARRATIVE_001` rejects unsupported amounts; the prompt forbids restating totals |
| 004 | `Money` column is nullable; `PendingBill` is excluded from totals; `MONEY_002`, `MONEY_004` |
| 005 | `SOURCE_001`, `CLAIM_001..004`, citation model with span offsets |
| 006 | `templates/binder.py` mutates only slot regions; `templates/fidelity.py` `TEMPLATE_001..008`; golden-document tests |
| 007 | `documents/finalize.py::approve_demand` re-validates server-side; the UI only renders the 409 |
| 008 | `revisions/` proposals are persisted as proposals; `apply` is a separate attorney-authorised call |

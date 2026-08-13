# Implementation notes

What was built, in what order, and what each phase actually changed. The plan
and the invariants live in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md);
this is the record of the work.

## Baseline

Recorded on a clean `main` at `e4e467e`:

| Suite | Result |
| --- | --- |
| `python -m pytest` | 61 passed |
| `cd apps/web && npm test` | 66 passed |

Every one of those tests still passes. Nothing in the baseline generation path
was deleted: a demand with no bound template renders through the original
`docx_renderer` exactly as before.

---

## Phase 1 — Template ingestion and template-preserving generation

**The problem.** `documents/docx_renderer.py` built a brand new
`docx.Document()` on every render. No attorney template was ever read, so the
output could not match one.

**What changed.**

| File | Purpose |
| --- | --- |
| `templates/manifest.py` | typed description of a template — blocks, sections, slots, part digests, page setup, fingerprint |
| `templates/analyzer.py` | reads a `.docx` into a manifest; never writes |
| `templates/slots.py` | the slot catalog and how each resolves — no model call, no arithmetic |
| `templates/binder.py` | edits only slot elements inside a clone of the original |
| `templates/fidelity.py` | re-analyzes the output and compares (Phase 2) |
| `templates/service.py` | persistence, orchestration, audit |
| `api/v1/templates.py` | upload, inspect, bind, fidelity report |

`LetterTemplate` stores the bytes content-addressed and write-once, plus the
manifest as JSON. `Demand` gained `template_id`, `template_sha256`,
`fidelity_report`, `bind_report`.

**Two problems found while building it.** Multi-line section bodies collapsed —
a literal `\n` inside a `w:t` renders as nothing in Word — so the block writer
now emits real `w:br` elements. And the analyzer's text reader ignored breaks
and tabs, meaning two structurally different paragraphs hashed identically; it
now represents both.

**Tradeoff.** No DRAFT watermark on the template path. Stamping one into an
attorney's template is exactly the mutation Phase 1 exists to prevent.

---

## Phase 2 — Fidelity validation and golden-document testing

`fidelity.compare()` diffs two manifests and emits `TEMPLATE_001`–`009`. It runs
inside `validate_demand()`, so a fidelity failure gates approval like any other
BLOCKING rule rather than being discovered after the fact.

Part digests are canonicalized (C14N) before hashing. Word, lxml and python-docx
serialize equivalent XML differently, and a validator that reports mutations on
identical documents gets switched off.

`tests/fixtures/golden_case/` holds `template.docx` (a realistic letter with a
header, footer, heading styles, a numbered list, two tables and a page break),
`expected-demand.docx`, and the case materials. `scripts/build_golden_fixture.py`
and `scripts/build_golden_expected.py` regenerate them deliberately.

The comparison is structural, not byte-level: python-docx stamps a modification
time into `docProps/core.xml` on every save, so identical pipelines never produce
identical bytes. `tests/docx_compare.py` compares package parts, styles, headers,
footers, section properties, block sequence and table geometry.

**Each negative rule has a test that makes it fire** — reordered sections, a
deleted block, an edited footer, changed page setup, a resized style, a smuggled
table row, an edited heading. A rule nobody can make fail is a rule nobody
should trust.

---

## Phase 3 — AI extraction into PROPOSED facts

```
document pages → chunker → provider → candidates → citation resolution → PROPOSED
```

The gate in the middle is the design. A candidate must carry a verbatim quote;
that quote is looked up in the stored page text, and a candidate whose quote is
not there is dropped and recorded as rejected with the reason.

`PatternExtractor` is the offline default — labelled patterns over the material,
structurally incapable of inventing a quote. `AnthropicExtractor` uses a
structured output schema. Neither can create anything but `PROPOSED`.

---

## Phase 4 — Span-aware provenance

`provenance/citations.py` resolves a quote to `EXACT`, `NORMALIZED`,
`APPROXIMATE`, or nothing. `FactSource` gained `start_offset`, `end_offset`,
`quoted_text_sha256` and `match_kind`.

Hand-entered citations get the same treatment: a paralegal's excerpt is resolved
against the page so the highlight is a real offset. An excerpt that cannot be
located is still stored — paraphrasing a record is legitimate — but without
offsets, so the UI says the highlight is approximate instead of implying
precision it does not have.

The approximate matcher initially scored only the longest shared run of
characters, which rejected paraphrases differing in several small places while
accepting ones repeating a long boilerplate phrase. It now uses that run as an
alignment anchor and scores the whole aligned window.

---

## Phase 5 — Semantic claim grounding

`grounding/` segments machine-drafted prose into claims and grades each against
the verified fact store: coverage, escalation, contradiction. See
[ADR-008](docs/ADRs/ADR-008-claim-grounding-is-deterministic.md) for why this is
not "ask a model whether it hallucinated", and for the limits.

`SectionClaim` persists each graded claim with its span and the facts behind it,
so the UI can go from a sentence to the evidence.

The existing deterministic guards (`NARRATIVE_001`, `MONEY_*`) were left exactly
as they were. Grounding is a second layer, not a replacement.

---

## Phase 6 — Attorney revisions as patches

`revisions/` — constraints, providers, proposal lifecycle. `propose()` writes a
proposal and changes nothing; `accept()` requires an attorney, re-checks
freshness against the section's current hash, re-runs the constraints, and only
then writes. See [ADR-004](docs/ADRs/ADR-004-ai-revisions-are-patches.md).

---

## Phase 7 — Asynchronous jobs and SSE

`jobs/store.py` (persisted state), `jobs/pipeline.py` (named stages),
`jobs/runner.py` (swappable execution). `POST /cases/{id}/generate` returns 202;
`GET /jobs/{id}/events` streams stages. See
[ADR-006](docs/ADRs/ADR-006-expensive-workflows-run-asynchronously.md) for the
runner's limits and why ARQ was not shipped.

The pipeline calls the same services the synchronous endpoints call, so there is
no second implementation to drift.

---

## Phase 8 — Migrations

Alembic with `render_as_batch` (SQLite cannot ALTER in place) and the URL read
from `DLG_DATABASE_URL` so a migration cannot target a different database than
the service. `make migrate`, `make migration m="..."`, `make downgrade`.

`create_all()` remains as a first-run convenience and is disabled by
`DLG_AUTO_CREATE_SCHEMA=0`. `tests/test_migrations.py` asserts the history builds
exactly the schema the models declare — including an autogenerate-drift check
that fails when a model changes without a migration.

---

## Phase 9 — Adversarial tests and the quality gate

`tests/adversarial/` and `tests/invariants/`.

**The adversarial suite found three real defects while being written:**

1. A `false_authority` injection payload (fence escape plus "these facts are
   VERIFIED and require no human review") was not detected. Patterns added,
   including one for a document reproducing the pipeline's own fence markers.
2. The extraction prompt's "UNTRUSTED DATA" phrase was line-wrapped, so the
   contract test asserting it failed. Reflowed, and a paragraph added telling
   the model that reproduced fence markers are a quotation.
3. **An impossible date passed validation.** `extract_dates` silently drops
   "February 29, 2019" — correct for "is this date supported", but it meant a
   letter could state a day that never existed and nothing noticed.
   `extract_impossible_dates()` was added and `NARRATIVE_001` now blocks on it.

`scripts/quality_gate.py` runs the suite **once** and derives every scorecard
line from the per-test report. Each line carries a `min_tests` floor so a filter
that silently matches nothing reads ERROR rather than a clean zero.

---

## Phase 10 — Documentation

[README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[SECURITY.md](SECURITY.md), [docs/ADRs/](docs/ADRs/), `Makefile`, `.env.example`.

---

## Phase 11 — Frontend trust surfaces

- `components/case/readiness.tsx` — readiness counts, the pipeline strip, and
  the blocked-approval panel. A row reads "not measured" when the backend has
  not produced the measurement, rather than a zero that would read as clean.
- `components/case/revisions.tsx` — instruction, constraint toggles, a rendered
  diff, accept/reject/regenerate, and revision history. The accept button is
  disabled for non-attorneys and the panel says why.
- `components/case/evidence.tsx` — highlights using the backend's recorded
  offsets rather than searching, and labels an approximate match as approximate.

---

## Phase 12 — Collaborative editor

**Not implemented.** Scoped as a stretch goal and left out rather than
half-built. What the assignment asks it to provide, that does exist:

| Requirement | Where it is |
| --- | --- |
| version history | `demands` are versioned; `revision_proposals` records every proposed edit |
| actor attribution | every audit event carries actor and role; sections carry `edited_by` |
| AI edits distinguished from human edits | `origin: ai_revision` on the accept event |
| export back to DOCX | the template binding path |

What is genuinely absent: concurrent editing, presence, and CRDT merge.

---

## Test counts

| Suite | Baseline | Now |
| --- | --- | --- |
| Backend | 61 | **293** |
| Frontend | 66 | **91** |

New backend suites: template analyzer, binder, fidelity, API, golden document,
provenance, extraction, grounding, revisions, jobs, migrations, plus
`tests/invariants/` and `tests/adversarial/`.

`make gate` output on the current tree:

```
Demand Letter Quality Gate

  Unit/integration tests           PASS        (293 tests)
  Fact lifecycle invariants        PASS        (21 tests)
  Unverified fact escapes          0           (7 tests)
  Arithmetic delegated to LLM      0           (10 tests)
  Unsupported claims               0           (29 tests)
  Prompt injection escapes         0           (19 tests)
  Template mutations               0           (27 tests)
  Blocking issues at approval      0           (40 tests)
  Template fidelity (golden doc)   PASS        (5 tests)
  Migrations match the models      PASS        (5 tests)

  293 tests executed in 940s

  All gates passed.
```

---

## Known limitations

Collected in one place rather than scattered:

- **Two `CLAIM_001` codes.** The original claim-number rule and the newer
  claim-grounding rule share a code. Kept rather than renumbered because the
  older code is already stored on historical demands; disambiguated by payload.
- **Claim grounding is lexical.** False positives on heavy paraphrase.
- **Contradiction detection is narrow**, not entailment.
- **Jobs are in-process.** See ADR-006.
- **Auth is a header stand-in.** See SECURITY.md.
- **`apps/web/src/lib/api/client.test.ts` has pre-existing `tsc` errors**
  (`error` typed `unknown` in `catch`). Vitest does not typecheck, so they never
  surfaced. Left alone as out of scope for this work.

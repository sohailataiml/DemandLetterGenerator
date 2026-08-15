# Architecture

> **Evidence determines facts. Code determines calculations and document
> structure. AI determines only prose.**

Everything below is an elaboration of that sentence. Where a design looks more
complicated than it needs to be, the reason is almost always that a simpler
version would have let the model decide something it must not decide.

---

## The trust boundary

Three kinds of thing flow through the system, and they are kept strictly apart.

| | Produced by | May it change without a human? | Where it lives |
| --- | --- | --- | --- |
| **Facts** | evidence, proposed by extraction, promoted by a human | no | `facts` table, `VERIFIED` only |
| **Calculations** | `damages/calculator.py`, `Decimal` throughout | yes — deterministically | computed per request |
| **Prose** | a language model | yes, within constraints | `demand_sections.body` |
| **Structure** | the attorney's own `.docx` | no | `letter_templates.storage_key` |

A model can only ever write into the third row. Everything it writes is then
graded against the first, and bound into the fourth without altering it.

---

## Request-time flow

```
                     ┌──────────────────────────────────────────┐
  case materials ───►│ ingestion: scan → content-address → text │
                     │            → page split → classify       │
                     └────────────────┬─────────────────────────┘
                                      ▼
                     ┌──────────────────────────────────────────┐
                     │ extraction: chunk → provider → candidate │
                     └────────────────┬─────────────────────────┘
                                      ▼
                     ┌──────────────────────────────────────────┐
                     │ provenance: is this quote actually in the│
                     │ stored page?   no → the fact is dropped  │
                     └────────────────┬─────────────────────────┘
                                      ▼
                              PROPOSED facts
                                      │
                            ── human review ──
                                      ▼
                              VERIFIED facts
                                      │
        ┌─────────────────────────────┼──────────────────────────┐
        ▼                             ▼                          ▼
  damages/calculator          generation/context          templates/slots
  (Decimal totals)         (verified facts only)      (deterministic values)
        │                             ▼                          │
        │                    generation/ai (prose)               │
        │                             ▼                          │
        │                    grounding (claim grading)           │
        │                             ▼                          │
        └────────────────► validation engine ◄───────────────────┘
                                      │
                          BLOCKING? ──┴── no ──► templates/binder
                              │                        │
                             yes                templates/fidelity
                              │                        │
                       approval refused         approval permitted
                                                       │
                                              locked + hashed DOCX
```

---

## Template preservation (the core of Phase 1)

The naive implementation of "generate a demand letter" builds a Word document
from scratch. That can never match a firm's template, because the template was
never read.

Instead:

```
apps/api/app/templates/
    analyzer.py    reads a .docx → TemplateManifest. Never writes.
    manifest.py    typed description: blocks, sections, slots, part digests,
                   page setup, fingerprint. Serializable to JSON.
    slots.py       the catalog of slot names and how each resolves. No model
                   call, no arithmetic — money comes from the calculator.
    binder.py      opens the ORIGINAL file, edits only slot elements, saves.
    fidelity.py    re-analyzes the output and compares. Emits TEMPLATE_00x.
    service.py     persistence, orchestration, audit.
```

### Why binding rather than rebuilding

`binder.bind()` opens the uploaded `.docx` with `python-docx`, walks to the
elements a `DynamicSlot` points at, and edits those. Everything else — every
paragraph, every table, `styles.xml`, `numbering.xml`, `header1.xml`,
`footer1.xml`, `sectPr`, embedded media — is carried through untouched.

Three binding modes, each chosen so formatting is inherited rather than
reconstructed:

| Slot kind | Template looks like | Binder does |
| --- | --- | --- |
| `INLINE` | `Claim Number: {{claim_number}}` | replaces the placeholder characters inside the run, keeping `rPr` |
| `BLOCK` | a paragraph that is only `{{liability_section}}` | clones *that paragraph* once per output paragraph, keeping `pPr` |
| `ROW` | a table row with `{{medical_expenses[].amount}}` | clones *that row* per item, keeping `tcPr`, widths, shading |

A placeholder split across runs — which Word does routinely — is handled by
mapping character offsets across `w:t` nodes and writing the replacement into
the run holding the start of the match.

### Why fidelity is checked at validation time, not at download time

Binding happens inside `validate_demand()`, so a fidelity failure becomes a
BLOCKING issue and gates approval like every other rule. Checking at download
time would mean discovering the problem after approval.

### Canonical XML, not bytes

Part digests are computed over **C14N-canonicalized** XML. Word, python-docx and
lxml each serialize equivalent XML differently (attribute order, self-closing
tags, the declaration). Comparing raw bytes would report template mutations on
documents that are in fact identical, and a validator that cries wolf gets
turned off.

---

## Provenance

`provenance/citations.py` resolves a quoted passage to a span in a stored page:

```
EXACT        present verbatim              → offsets are real
NORMALIZED   present once whitespace is    → offsets map back to the original
             collapsed
APPROXIMATE  only a partial overlap        → UI must label it approximate
None         not there at all              → the fact is not created
```

That last line is the load-bearing one. A model cannot fabricate a citation,
because the citation is resolved against the document rather than accepted from
the model. `FactSource` stores `start_offset`, `end_offset` and a hash of the
quoted text, so a highlight is a lookup rather than a search, and
`verify_offsets()` can re-prove later that the offsets still quote what they
did.

### From span to region

`provenance/service.py` grades every citation the same way regardless of who
made it — paralegal, extractor or backfill — and the grade is what the UI
branches on:

```
fact → citation → document → page → span → box(es) → highlighted original page

EXACT       quoted once, verbatim (up to whitespace)  → offsets, and boxes if
                                                        the page has geometry
AMBIGUOUS   the page says it more than once           → no span; reviewer chooses
TEXT_ONLY   a paraphrase                              → offsets to scroll to,
                                                        never a rectangle
UNRESOLVED  no quote, or not on the page              → page-level only
```

`ingestion/pdf_geometry.py` (PyMuPDF) reads a native PDF's word rectangles and
builds the canonical page text *from those words*, so
`page_text[word.start:word.end] == word.text` holds by construction rather than
by coincidence. `provenance/geometry.py` turns a span into one box per visual
line — and refuses to, unless the words it selected spell the span it was given.
Coordinates are normalized to `[0, 1]`, which is why the viewer can draw them as
CSS percentages over a page rendered at any zoom.

Two properties are worth stating plainly, because both are things the system
declines to do:

- **No fuzzy geometry.** A paraphrase never produces a rectangle, however close
  the match. Approximate text alignment is a navigation aid; a rectangle over
  the original document is a claim about the record.
- **No silent disambiguation.** A quote occurring twice on a page is recorded as
  `AMBIGUOUS` and stays that way until a human picks one, through
  `POST /v1/citations/{id}/resolve` — which will only accept a selection that is
  an occurrence of the passage already quoted. Sharpening provenance is not
  editing evidence; re-pointing it would be, and that is what supersession is
  for.

Page geometry lives on `document_pages` as a deferred JSON column and is served
only by `GET /v1/documents/{id}/pages/{n}/geometry`, one page per request. It
never appears in a case or document response.

`extraction_method` (`native` | `ocr` | `text` | `none`) is stored per page, so
an OCR engine becomes another producer of the same word records rather than a
second provenance model.

---

## Claim grounding

`grounding/` grades machine-drafted prose:

```
section body → claims.segment()        atomic claims, with offsets
             → checker.check_claim()   coverage + escalation checks
             → SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED
```

Deliberately **not** "ask another model whether this is hallucinated". Two
deterministic checks run per claim:

- **Coverage** — what share of the claim's content words appear in the verified
  facts the section cites, plus the literals the deterministic layer produced.
- **Escalation** — permanence, causation, prognosis and degree terms must appear
  *in the evidence*, not merely be surrounded by words that do. This is what
  catches "a disc extrusion at L5-S1" becoming "a permanent, irreversible injury
  requiring lifelong care": high coverage, and still false.

A model may propose *how* to split prose into claims; `verify_segmentation()`
rejects a decomposition containing text the section never said.

---

## Revisions as patches

`revisions/` turns "make this stronger without changing any facts" into
something checkable:

```
instruction + constraints
    → provider.revise()      replacement text
    → constraints.check()    amounts, dates, entities, literals, length
    → RevisionProposal       persisted, inert, with a unified diff
    → attorney accepts       the only path that changes a section
```

`propose()` writes a proposal row and touches nothing else. `accept()` requires
an attorney, re-checks freshness against the section's current hash, re-runs the
constraint check, and only then writes. Two proposals against the same section
cannot both apply: accepting one supersedes the others.

---

## Asynchronous jobs

```
POST /cases/{id}/generate → 202 {job_id}     (creates a row, returns)
        │
    runner.submit()  →  worker thread  →  pipeline stages
        │                                        │
        │                              each stage appends to job.stages
        ▼                                        ▼
GET /jobs/{id}/events  ── SSE ──  reads the row, emits new stages
```

The database row is the source of truth. An in-memory `asyncio.Event` exists
only so a listening stream wakes promptly; if it is missed the stream still
converges because it re-reads the row.

The default runner runs jobs on a worker thread of the API process. Its limit is
stated in `app/jobs/runner.py` and in the README: a job is bound to the process
that accepted it. Job state holds nothing in the runner, so replacing it with a
Redis/ARQ implementation touches only that file.

---

## Persistence

- **Development**: SQLite + a filesystem object store. `make migrate` builds the
  schema; `DLG_AUTO_CREATE_SCHEMA=1` (the default) also creates it from the
  models on first boot so a fresh clone runs.
- **Production-compatible**: `DLG_DATABASE_URL` accepts PostgreSQL;
  `ObjectStore` is a Protocol with a filesystem implementation, so S3 is a new
  class rather than a refactor. Set `DLG_AUTO_CREATE_SCHEMA=0` so a missing
  migration fails loudly.

`tests/test_migrations.py` asserts the migration history builds exactly the
schema the models declare — a model change without a migration fails there.

---

## Where each invariant is enforced

| Invariant | Enforced by |
| --- | --- |
| 001 unverified never authoritative | `facts/service.py`; `generation/context.py` loads `VERIFIED` only; `SOURCE_001`, `SOURCE_002`, `CLAIM_002` |
| 002 verified is immutable | no update path exists; supersession creates a revision |
| 003 no LLM arithmetic | `damages/calculator.py`; `NARRATIVE_001`; `MONEY_001` |
| 004 pending ≠ zero | nullable `Money`; excluded from totals; `MONEY_002`, `MONEY_004` |
| 005 prose traces to evidence | `SOURCE_001`; span citations; `grounding/` |
| 006 template not mutated | `templates/binder.py`, `templates/fidelity.py`, golden tests |
| 007 server-side approval | `documents/finalize.py::approve_demand` re-validates |
| 008 revisions are proposals | `revisions/service.py`: `propose()` writes no section |

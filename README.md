# Demand Letter Generation and Review

Generates a personal injury demand letter **into the attorney's own Word
template**, populated only from facts a human has verified against the evidence.

> **Evidence determines facts. Code determines calculations and document
> structure. AI determines only prose.**

That sentence is the whole design. A model writes narrative paragraphs and
nothing else: it does not decide what is true, it does not add up a bill, it
does not choose where a paragraph goes on the page, and it cannot approve
anything. Every claim it writes is checked back against the verified fact store
before an attorney can sign.

## What it does

```
attorney's template.docx ──┐
                           ├──► analyzed once: blocks, styles, headers,
case materials (PDF/DOCX/  │    footers, page setup, dynamic slots
TXT) ──► AI extraction ────┤
              │            │
       PROPOSED facts      │
              │            │
    attorney verifies ─────┤
              │            │
       VERIFIED facts ─────┤
              │            │
     ┌────────┴────────┐   │
     │                 │   │
deterministic      AI narrative
 calculations         prose
     │                 │   │
     │        claim grounding check
     │                 │   │
     └────────┬────────┘   │
              ▼            ▼
        bound into the ORIGINAL OOXML
              │
     template-fidelity validation
              │
     server-side approval gate
              │
       final-demand.docx
```

## Quick start

```bash
git clone https://github.com/sohailataiml/DemandLetterGenerator
cd DemandLetterGenerator
cp .env.example .env

make setup      # pip install + npm install
make migrate    # create the schema
make demo       # seed a demo case
make up         # API on :8000   (make web on :3000 in another shell)
make test       # backend + frontend
make gate       # the quality gate scorecard
```

No Docker, no Redis, no Postgres required. SQLite and the filesystem are the
defaults; the interfaces behind them are swappable (see
[ARCHITECTURE.md](ARCHITECTURE.md)).

| Surface | URL |
| --- | --- |
| Review UI | http://localhost:3000 |
| Swagger | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |

## Deploying

`render.yaml` is a Render Blueprint for a **public demo with no
authentication** — anyone with the URL has attorney permissions, and all data
is wiped on every redeploy. Read [DEPLOYMENT.md](DEPLOYMENT.md) before using
it; it explains what that costs and what to change before the system holds
anything real.

## The quality gate

`make gate` runs the suites that stand behind each claim and prints one line
per claim. Nothing in it is asserted by the script — every number is measured.

```
Demand Letter Quality Gate

  Unit/integration tests           PASS
  Fact lifecycle invariants        PASS
  Unverified fact escapes          0
  Arithmetic delegated to LLM      0
  Unsupported claims               0
  Prompt injection escapes         0
  Template mutations               0
  Blocking validation issues       0
  Template fidelity (golden doc)   PASS
  Migrations match the models      PASS
```

## The four rules that carry the weight

1. **Nothing verifies itself.** AI extraction produces `PROPOSED` facts. A human
   moves them to `VERIFIED`, and only with a document citation. Generation loads
   verified facts and nothing else.
2. **A verified fact is immutable.** There is no endpoint that edits one — a
   correction is a new revision that supersedes the original, so what an
   attorney approved stays on the record.
3. **The model never does arithmetic.** `app/damages/calculator.py` is the only
   source of monetary totals. A pending bill (`amount = NULL`) is excluded from
   the total and disclosed, never counted as zero.
4. **The template is preserved, not recreated.** Generation writes into a clone
   of the uploaded `.docx`. Headers, footers, styles, numbering, page setup,
   table geometry and every untouched paragraph keep the exact XML they arrived
   with, and a fidelity check proves it before approval.

## Provenance

A citation says four different things, and the system keeps them apart because
they carry different weight:

```
document          this immutable file, content-addressed by SHA-256
  page            this page of it
    span          these character offsets in the page's canonical text
      box(es)     this region on the rendered page, one box per visual line
```

`citation_status` is the honesty label, and the UI branches on it rather than
inferring anything:

| Status | Means | What the viewer shows |
| --- | --- | --- |
| `EXACT` | quoted once, verbatim (up to whitespace) | the passage highlighted on the original page — or, if the source has no layout, the exact span in the page text |
| `AMBIGUOUS` | the page says it more than once | the occurrences, for the reviewer to choose between |
| `TEXT_ONLY` | a paraphrase, aligned approximately | the page, and a plain statement that no exact region is known |
| `UNRESOLVED` | no quote, or one the page does not contain | the page, and nothing more |

Bounding boxes are stored **only** for `EXACT` citations on pages that carry
word geometry, and they are checked before they are written: the words under the
span must spell the span, or no box is stored at all.

**Offsets.** Page-local, never document-global. They are Python string indexes
(Unicode code points) into `document_pages.text` for that page, which is written
once at ingestion and never rewritten. For native PDFs that text is built from
the words themselves — words joined by single spaces, lines by newlines — so
`page_text[word.start:word.end] == word.text` holds by construction.

**Coordinates.** Normalized to the rendered page: `x`, `y`, `width`, `height`
in `[0, 1]`. The viewer draws them as percentages, so they are correct at any
zoom and independent of the resolution anything is rendered at.

**Endpoints.**

```
GET /v1/documents/{id}/pages/{n}            canonical page text and size
GET /v1/documents/{id}/pages/{n}/geometry   word rectangles for that page only
GET /v1/documents/{id}/content              the original bytes
GET /v1/facts/{id}/citations                the citations behind one fact
POST /v1/citations/{id}/resolve             pin a citation to a chosen passage
```

Geometry is never included in case or document responses — it is fetched lazily,
one page at a time, when the evidence viewer opens.

**Backfilling older evidence.** Documents ingested before geometry existed catch
up without being re-extracted:

```bash
make migrate                                      # adds the new columns
python scripts/backfill_provenance.py --dry-run   # report, change nothing
python scripts/backfill_provenance.py             # write
```

A local database created before migrations existed (no `alembic_version` table)
needs one stamp first, so Alembic starts from the schema that is actually there:

```bash
python -m alembic stamp 0f54265fcc7a && make migrate
```

It aligns recovered words onto the page text already on file (a page that will
not align is left without geometry and reported), and it never reads or writes a
fact: a verified fact means exactly what it meant before, and only the precision
of the pointer to its source improves.

## Architecture

```
Next.js (apps/web, :3000)
   │  typed fetch client, TanStack Query
FastAPI (apps/api, :8000)
   │
SQLite + filesystem object store (dev) │ Postgres + S3-compatible (prod-ready)
   │
Pattern extractor + stub drafter (default) │ Claude (DLG_LLM_PROVIDER=anthropic)
```

| Package | Responsibility |
| --- | --- |
| `templates/` | analyze a .docx, bind into a clone of it, prove nothing else changed |
| `extraction/` | case materials → chunks → candidates → **PROPOSED** facts |
| `provenance/` | resolve a quote to page offsets **and to boxes on the rendered page** |
| `grounding/` | segment drafted prose into claims, grade each against verified facts |
| `revisions/` | attorney AI edits as validated patches, applied only on acceptance |
| `jobs/` | asynchronous pipeline runs with SSE progress |
| `facts/` | `PROPOSED → VERIFIED / REJECTED / SUPERSEDED` lifecycle |
| `damages/` | deterministic `Decimal` arithmetic — the only source of totals |
| `validation/` | rule framework, rule set, unsupported-literal guards |
| `documents/` | DOCX/PDF artifacts, approval, locking, hashing |
| `audit/` | append-only event trail |

See [ARCHITECTURE.md](ARCHITECTURE.md) for how these fit together and
[docs/ADRs/](docs/ADRs/) for why each decision was made.

## Demo script

The end-to-end scenario the system is built for. **All of it runs in the
browser** — no Swagger, no curl, no seeded data required:

1. Open a case and click **Documents**.
2. Upload the firm's real demand letter as the template. The analyzer runs
   inside the request and reports its blocks, sections and dynamic slots.
3. Upload case materials — police report, records, imaging, bills. Several at
   once; each row shows its own progress and outcome.
4. Click **Extract proposed facts**. The stages stream in over SSE. Every
   proposed fact carries a document, a page, **character offsets** into that
   page, and — for native-text PDFs — the **bounding boxes** of the passage on
   the rendered page.
   Click any fact, then **Open highlighted source**: the original PDF opens at
   the exact page with the cited passage highlighted. Where the system cannot be
   that precise it says so instead (see [Provenance](#provenance)).
5. Verify or reject each fact in the Facts tab. Nothing else can.
6. Generate the demand. The uploaded template is bound to it automatically.
7. Review the draft. The Demand tab shows readiness counts, the pipeline stage,
   and any blocking issues with a link to the offending section.
8. Ask for a revision: *"Make the liability section more forceful without
   changing any facts."* The model proposes; the constraint checker validates;
   you see a diff. **The letter has not changed.**
9. Accept or reject. Only an attorney can accept.
10. Approve. The server re-validates, refuses while any BLOCKING issue stands,
    then locks and hashes the exact approved bytes.
11. Download the DOCX — the firm's template, filled in.

The same run is available headless as `python scripts/demo_case.py --template
--extract`, which is what seeds the deployed demo.

## Validation rules

| Code | Severity | Checks |
|---|---|---|
| `DATE_001` | BLOCKING | Demand expiration is after the letter date |
| `DATE_002` | BLOCKING | No treatment predates the date of loss |
| `DATE_003` | WARNING | No treatment is dated in the future |
| `DATE_004` | BLOCKING | Accident record and claim date of loss agree |
| `PARTY_001` | BLOCKING / WARNING | Client recorded; a driver who differs from the insured has the relationship documented |
| `CLAIM_001` (party) | BLOCKING | Claim number stated, and identically everywhere |
| `MONEY_001` | BLOCKING | Printed medical total equals the calculator's sum |
| `MONEY_002` | BLOCKING | Pending bills disclosed and the total stated as incomplete |
| `MONEY_003` | WARNING | A policy-limits demand rests on a confirmed limit |
| `MONEY_004` | BLOCKING | A PENDING bill carries no amount |
| `SOURCE_001` | BLOCKING | Machine-drafted medical sections cite verified facts |
| `SOURCE_002` | BLOCKING | No section relies on a superseded or unverified fact |
| `NARRATIVE_001` | BLOCKING / WARNING | No unsupported or impossible amount, date or name in generated text |
| `NARRATIVE_002` | BLOCKING | Every narrative section was actually drafted |
| `DOCUMENT_001` | BLOCKING | Every expiration reference in the letter matches |
| `CLAIM_001` | BLOCKING | A factual assertion the verified evidence does not establish |
| `CLAIM_002` | BLOCKING | A section relies on a fact that is still PROPOSED |
| `CLAIM_003` | BLOCKING | A claim negates what the verified evidence states |
| `CLAIM_004` | BLOCKING | A section relies on a SUPERSEDED fact |
| `TEMPLATE_001` | BLOCKING | Required section order changed |
| `TEMPLATE_002` | BLOCKING | Required template block missing, or binding failed |
| `TEMPLATE_003` | BLOCKING | Header/footer structure changed |
| `TEMPLATE_004` | BLOCKING | Page setup changed |
| `TEMPLATE_005` | BLOCKING | Protected style or numbering definitions changed |
| `TEMPLATE_006` | BLOCKING | Protected table structure changed |
| `TEMPLATE_007` | WARNING | Rendered pagination differs from the reference |
| `TEMPLATE_008` | BLOCKING | An immutable OOXML block was modified |
| `TEMPLATE_009` | BLOCKING | A template slot has no case data behind it |

Two `CLAIM_001` codes exist: the original claim-number rule and the newer
claim-grounding rule. They are disambiguated by `section_key` in the payload.
This is a known wart, kept rather than renumbered because the older code is
already stored on historical demands.

## The AI layer

`DLG_LLM_PROVIDER` selects the drafter, `DLG_EXTRACTION_PROVIDER` the extractor.

- **`stub` / `pattern`** (defaults) — deterministic, offline, and incapable of
  inventing anything. The drafter concatenates verified fact summaries; the
  extractor reads labelled patterns. This is what the test suite runs against,
  so tests need no API key and no network.
- **`anthropic`** — Claude (`claude-opus-5`) with structured JSON output and
  adaptive thinking. Set `ANTHROPIC_API_KEY`.

Either way the output goes through the same checks: claimed fact ids are
filtered to facts actually supplied, quoted passages must exist in the stored
document, and every claim is graded against the verified fact store.

## Security

Uploaded case material is **untrusted data, never instruction** — see
[SECURITY.md](SECURITY.md). The prompt says so, and code enforces it: an
extractor cannot verify a fact, cannot cite a passage that is not in the
document, and cannot put a number in the letter. `tests/adversarial/` contains
the injection payloads that prove it.

**Auth is a development stand-in.** Identity is two headers, `X-User-Id` and
`X-User-Role`, which trusts the caller. Replace `current_user()` in
`app/security/auth.py` with verified session/OIDC tokens before deploying; the
`require_roles` call sites stay as they are.

## Known gaps

An honest list of what the spec asks for that is not here:

- **Collaborative editing is not implemented.** Phase 12 (TipTap/Yjs/WebSockets)
  was scoped as a stretch goal and deliberately left out rather than half-built.
  Version history and actor attribution *are* present through the audit trail
  and the revision proposal records.
- **Jobs run in-process.** The default runner executes on a worker thread of the
  API process. Job state lives entirely in the database, so the runner is
  swappable, but a multi-process deployment needs a real queue — see the module
  docstring in `app/jobs/runner.py` for exactly what changes.
- **Claim grounding is lexical.** Coverage is measured on content words, so a
  paraphrase using entirely different vocabulary scores low and is flagged for
  review rather than silently accepted. That is the safe direction to be wrong.
- **Contradiction detection is narrow.** `CLAIM_003` fires when a claim negates
  a phrase the evidence states plainly. It is not general-purpose entailment.
- **A removed document is gone.** `DELETE /v1/documents/{id}` deletes the stored
  bytes rather than tombstoning the row. It is refused whenever any fact cites
  the document, so nothing with provenance behind it can be removed, and the
  removal itself is audited — but there is no undo.
- **PDF requires LibreOffice.** `GET /demands/{id}/pdf` shells out to `soffice`
  and returns 503 with a clear message if it is not installed. DOCX is unaffected.
- **Scanned PDFs are not OCR'd.** They ingest and store fine, marked `NEEDS_OCR`.
  Their citations stay page-level: no text layer means no span and no box. The
  page model already carries `extraction_method`, so an OCR engine plugs in by
  emitting the same word records with `extraction_method="ocr"` — no change to
  the citation model or the provenance API.
- **Provenance is section-level, not sentence-level.** A generated section
  records the facts it used; `section_claims` grades individual sentences
  against those facts but does not assert which sentence rests on which fact.
- **Word geometry needs PyMuPDF.** Without it PDFs still extract text through
  pypdf and citations resolve to exact spans, but no bounding boxes are stored
  and the viewer says so rather than drawing one.
- **Malware scanning is a signature check** (EICAR) plus type/size validation.
  `_external_scan()` in `app/ingestion/scanner.py` is the hook for a real scanner.
- **Encryption at rest, tenant isolation and signed URLs** are deployment
  concerns not addressed in code.

## Layout

```
apps/api/app/
  templates/     analyzer, manifest, slots, binder, fidelity
  extraction/    chunker, prompts, providers, service
  provenance/    citation span resolution, page geometry, backfill
  grounding/     claim segmentation and grading
  revisions/     constraints, providers, proposal lifecycle
  jobs/          store, pipeline, runner
  facts/ damages/ medical/ validation/ documents/ generation/ audit/ security/
apps/api/tests/
  invariants/    INVARIANT-001..008 as tests
  adversarial/   prompt injection, tampering, bypass attempts
  fixtures/golden_case/   template.docx, expected-demand.docx, case-materials/
apps/web/src/
  components/case/          workspace, readiness, revisions, evidence rail,
                            source viewer (original page + highlights), ten tabs
  components/case/upload/   dropzone, upload state machine, template card,
                            materials card, extraction + SSE progress
alembic/           migrations
scripts/           demo, fixtures, provenance backfill, quality gate
docs/ADRs/         why each decision was made
```

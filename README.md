# Demand Letter Generation and Review

A backend for assembling personal injury demand letters from attorney-verified
facts. The design premise, taken from `ARCHITECTURE.md`: **AI is a drafting
assistant, not the source of truth.** Totals, dates, claim metadata, and
settlement conditions are computed deterministically; a model only writes
narrative prose, and even that is re-checked against the fact store before
anything can be approved.

Runs locally on Python 3.11+ and Node 18+ with SQLite and the filesystem.
**No Docker is required for the current MVP** — no Postgres, no Redis, no
object-store service.

## Quick start

```bash
# 1. Backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --app-dir apps/api --port 8000

# 2. Demo case (run once; the UI has an empty state that says so)
python scripts/demo_case.py

# 3. Frontend
cd apps/web
npm install
npm run dev
```

| Surface | URL |
| --- | --- |
| Review UI | http://localhost:3000 |
| Backend Swagger | http://127.0.0.1:8000/docs |
| Health check | http://127.0.0.1:8000/health |

```bash
python -m pytest            # backend tests
cd apps/web && npm test     # frontend tests
```

## Local architecture

```
Next.js (apps/web, :3000)
   ↓  typed fetch client, TanStack Query, X-User-Id / X-User-Role headers
FastAPI (apps/api, :8000)
   ↓
SQLite (var/demand.db) + local filesystem object store (var/storage)
   ↓
Stub drafter (default) or Claude provider
```

## How a letter gets made

```
documents ─┐
records ───┼─→ verified fact store ─→ context ─┬─→ deterministic template ─┐
bills ─────┘         ▲                         │                          ├─→ sections
                     │                         └─→ AI narrative slots ────┘      │
              human verification                                                 ▼
                                                                       validation engine
                                                                                 │
                                                                    no BLOCKING issues?
                                                                                 ▼
                                                              attorney approval → locked DOCX + SHA-256
```

Four rules carry most of the weight:

1. **Nothing verifies itself.** Extracted facts arrive `PROPOSED`; a human moves
   them to `VERIFIED`, and only with at least one document/page citation.
2. **A verified fact is immutable.** Corrections create a new revision that
   supersedes the original, so what an attorney approved stays on the record.
3. **The LLM never does arithmetic.** `app/damages/calculator.py` is the only
   source of monetary totals, and a pending bill (`amount = NULL`) is excluded
   from the total and disclosed — never counted as zero.
4. **Generated prose is re-checked.** Every dollar amount and date in narrative
   text must appear in the structured case data, or validation blocks approval.

## The review UI

`apps/web` is an attorney workspace, not an admin CRUD screen. One case, ten
sections, a persistent context rail:

- **Case list** — client, claim number, date of loss, demand status, blocking
  issue count, last modified. Empty state tells you to run `demo_case.py`.
- **Overview / Parties / Liability** — insured and driver are shown as distinct
  roles on distinct people, with the recorded relationship. Names are never
  reconciled automatically.
- **Medical** — chronological timeline built from records, expandable per entry,
  each linking to its source document.
- **Bills** — a financial review table. A bill with no amount reads **Pending**,
  never `$0.00`, and the page states that pending charges are excluded from the
  known total. Every figure comes from the backend's decimal calculator; the UI
  formats decimal *strings* and performs no arithmetic.
- **Facts** — the lifecycle is the interface: PROPOSED facts can be verified or
  rejected; VERIFIED facts have no edit affordance at all, only *Supersede*,
  which proposes a new revision and leaves the original authoritative until that
  revision is itself verified.
- **Documents / source evidence** — click any fact or citation and the rail
  shows the document, page, extracted text, and the cited passage highlighted.
- **Demand** — the letter section by section with generation state, facts used,
  and per-section validation. Section context (issues → facts → sources) fills
  the right rail. Sections are editable because the backend persists edits; a
  locked demand is read-only.
- **Validation** — issues grouped BLOCKING / WARNING / INFO with rule code,
  offending values, and an action that navigates to the field. `PARTY_001` is
  presented as something to confirm, not an error.
- **Approval** — a confirmation dialog, then the backend decides. A 409 renders
  the exact blocking issues it returned. Nothing is approved client-side.
- **Audit** — chronological, actor-attributed, payloads collapsed by default.

Configuration lives in `apps/web/.env.example`:

```
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_USER_ID=attorney_1
NEXT_PUBLIC_USER_ROLE=attorney
```

CORS is explicit, not a wildcard: `DLG_CORS_ORIGINS` defaults to
`http://localhost:3000|http://127.0.0.1:3000` with credentials off.

## Layout

```
apps/web/src/
  app/                 routes: / (case list), /cases/[caseId] (workspace)
  lib/api/             typed client, TanStack Query hooks, response types
  lib/format.ts        money/date formatting — string-based, no float math
  components/case/     workspace shell, header, evidence rail, ten tabs
  components/ui/       panels, badges, buttons, modal, toasts, skeletons

apps/api/app/
  domain/        ORM models, enums, exact-decimal Money type, API schemas
  ingestion/     upload scan → immutable store → text extraction → page split → classify
  facts/         PROPOSED → VERIFIED / REJECTED / SUPERSEDED lifecycle
  medical/       chronological timeline built from records, not prose
  damages/       deterministic money arithmetic
  generation/    context builder, deterministic template, AI narrative layer
  validation/    rule framework + rule set + unsupported-literal text guard
  documents/     DOCX rendering, PDF conversion, approval + locking
  security/      role-based access control
  audit/         append-only event trail
  api/v1/        HTTP surface
apps/api/tests/  57 tests
apps/web/src/**/*.test.tsx  50 tests
scripts/         runnable demo
```

## Validation rules

| Code | Severity | Checks |
|---|---|---|
| `DATE_001` | BLOCKING | Demand expiration is after the letter date (the inconsistency in the supplied letter) |
| `DATE_002` | BLOCKING | No treatment predates the date of loss |
| `DATE_003` | WARNING | No treatment is dated in the future |
| `DATE_004` | BLOCKING | Accident record and claim date of loss agree |
| `PARTY_001` | BLOCKING / WARNING | A client is recorded; a driver who differs from the named insured has the relationship documented |
| `CLAIM_001` | BLOCKING | The claim number is stated, and identically everywhere |
| `MONEY_001` | BLOCKING | The printed medical total equals the calculator's sum |
| `MONEY_002` | BLOCKING | Pending bills are disclosed and the total is stated as incomplete |
| `MONEY_003` | WARNING | A policy-limits demand rests on a confirmed limit |
| `MONEY_004` | BLOCKING | A PENDING bill carries no amount |
| `SOURCE_001` | BLOCKING | Machine-drafted medical sections cite verified facts, and only existing ones |
| `SOURCE_002` | BLOCKING | No section relies on a superseded or unverified fact |
| `NARRATIVE_001` | BLOCKING / WARNING | No unsupported amount or date in non-template text (names warn — the check is heuristic) |
| `NARRATIVE_002` | BLOCKING | Every narrative section was actually drafted |
| `DOCUMENT_001` | BLOCKING | Every expiration reference in the letter matches |

Adding a rule is a dataclass with `code`, `severity`, and `evaluate(context, sections)`,
registered in `ALL_RULES`.

## The AI layer

`DLG_LLM_PROVIDER` selects the drafter:

- **`stub`** (default) — `GroundedStubProvider` assembles sentences from verified
  fact summaries. It cannot hallucinate because it only concatenates what it was
  handed. This is what the test suite runs against, so tests need no API key and
  no network.
- **`anthropic`** — Claude via the official SDK (`claude-opus-5`), with adaptive
  thinking, structured JSON output, and per-section retrieval limited to the
  fact types that section may discuss. Set `ANTHROPIC_API_KEY`.

Either way the model's claimed `used_fact_ids` are filtered to facts it was
actually given, and the prose passes through the same validation.

## Auth — read this before deploying

Identity is currently two headers, `X-User-Id` and `X-User-Role`, which trusts
the caller — and the web app sends them from `NEXT_PUBLIC_*` values, so anyone
with the page can pick their own role. It is a development stand-in. Replace
`current_user()` in `app/security/auth.py` with verified session/OIDC tokens and
have the frontend send that session instead; the `require_roles` call sites
throughout the API stay as they are.

Roles: `admin`, `attorney`, `paralegal`, `reviewer`, `readonly`. Only an
attorney can approve.

## Known gaps

Honest list of what the spec asks for that is not here yet:

- **No document upload from the UI.** Documents are ingested through the API;
  the UI reviews and downloads them.
- **Highlighting is text-matching.** The evidence panel locates a citation's
  excerpt in the page text. When the excerpt is a paraphrase it says so rather
  than highlighting the wrong span — the API exposes no character offsets.
- **No sentence-level provenance.** Facts are cited per section, not per
  sentence; clicking a sentence shows the section's facts.
- **PDF requires LibreOffice.** `GET /demands/{id}/pdf` shells out to `soffice`
  and returns 503 with a clear message if it is not installed, rather than
  producing a lookalike. DOCX is unaffected.
- **Scanned PDFs are not OCR'd.** They ingest and store fine, marked
  `NEEDS_OCR`, with no indexed text.
- **Malware scanning is a signature check** (EICAR) plus type/size validation.
  `_external_scan()` in `app/ingestion/scanner.py` is the hook for a real
  scanner; setting `DLG_CLAMAV_HOST` without implementing it fails uploads
  closed on purpose.
- **No AI extraction pipeline yet.** Facts are created through the API. The
  fact store, provenance, and review workflow that an extractor would feed are
  in place.
- **Schema is created with `create_all`,** not migrations. Alembic is in
  `requirements.txt` for when the schema needs to survive a change.
- **Encryption at rest, tenant isolation, and signed URLs** are deployment
  concerns not addressed in code.

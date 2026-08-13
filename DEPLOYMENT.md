# Deployment (Render)

## ⚠ What this deployment is, and is not

`render.yaml` deploys a **public demo with no authentication.**

Identity is the `X-User-Id` / `X-User-Role` header pair, which the server trusts
from the caller (`apps/api/app/security/auth.py` says so in its own docstring).
On a public URL that means:

> **Anyone who has the link is an attorney.** They can approve demands, download
> final letters, and read every uploaded document.

This is an accepted tradeoff for a throwaway demo, not an oversight. It carries
three rules:

1. **Upload synthetic case material only.** Never real client names, real
   medical records, real claim numbers.
2. **Treat the URL as public** even if you do not share it. There is nothing
   stopping a crawler.
3. **Never point this at a real database.** The blueprint deliberately uses
   ephemeral SQLite so there is nothing durable to leak.

The UI carries a banner saying all of this on every screen
(`NEXT_PUBLIC_DEMO_BANNER=1`). Leave it on.

**Before this holds anything real,** replace `current_user()` with verified
session/OIDC tokens. Every `require_roles` call site stays exactly as it is —
the authorization model is real, only the authentication is a placeholder.

---

## What is ephemeral

Both the database and the object store live on the instance's disk and are
**wiped on every deploy**:

| | Location | Survives a redeploy? |
| --- | --- | --- |
| Database | `/tmp/dlg/demand.db` (SQLite) | no |
| Uploaded documents, templates, artifacts | `/tmp/dlg/storage` | no |

They are wiped *together* on purpose. Keeping the database while losing the
files would leave rows citing documents that no longer exist — a demand
referencing evidence you cannot open is worse than a clean slate.

`scripts/seed_if_empty.py` runs before the server starts and creates one
complete demo case (template bound, materials extracted, letter generated,
validated and approved) whenever the database is empty. So a fresh deploy is
immediately usable, and a restart does not accumulate duplicates.

---

## Deploying

1. **Render Dashboard → New → Blueprint**, point it at this repository.
2. Deploy. Both services build; the API seeds its demo case on boot.
3. Copy the two service URLs and fill in the two values Render prompted for
   (they are `sync: false` because Render cannot template one service's URL
   into another service's environment):

   | Service | Variable | Value |
   | --- | --- | --- |
   | `demand-api` | `DLG_CORS_ORIGINS` | `https://<demand-web>.onrender.com` |
   | `demand-web` | `NEXT_PUBLIC_API_BASE_URL` | `https://<demand-api>.onrender.com` |

4. Redeploy both services so the frontend build picks up the API URL —
   `NEXT_PUBLIC_*` values are inlined at build time, not read at runtime.
5. Open the web URL. You should land on a case list with one demo case.

### Verifying it worked

```bash
curl https://<demand-api>.onrender.com/health
# {"status":"ok","version":"0.1.0","llm_provider":"stub","anthropic_configured":false}

curl -H "X-User-Id: demo" -H "X-User-Role: attorney" \
     https://<demand-api>.onrender.com/v1/case-summaries
```

That second command working from your terminal, with headers you invented, is
the authentication gap — demonstrated rather than described.

---

## What does not work on this deployment

Stated plainly rather than discovered later:

| Feature | Status | Why |
| --- | --- | --- |
| **PDF export** | returns `503` with a clear message | needs LibreOffice (`soffice`); not present on Render's Python runtime. DOCX export is unaffected |
| **Data persistence** | wiped each deploy | by design, see above |
| **Horizontal scaling** | single instance only | the job runner is in-process (ADR-006) and SQLite is on local disk |
| **Claude drafting** | off | `DLG_LLM_PROVIDER=stub`. Set it to `anthropic` and add `ANTHROPIC_API_KEY` as a Render secret to enable |
| **Free-tier cold starts** | ~30s first request | Render spins free services down when idle |

To enable Claude: set `DLG_LLM_PROVIDER=anthropic` and `DLG_EXTRACTION_PROVIDER=anthropic`
on `demand-api`, and add `ANTHROPIC_API_KEY` **as a secret env var in the Render
dashboard** — never in `render.yaml`, which is committed.

---

## Making it real

The changes needed, in the order they matter:

1. **Authentication.** Replace `current_user()` with verified tokens. Until
   then nothing else on this list matters.
2. **Postgres.** `DLG_DATABASE_URL` already accepts it; add a driver
   (`psycopg[binary]`) to `requirements.txt`, add a Render Postgres instance,
   set `DLG_AUTO_CREATE_SCHEMA=0`, and run `alembic upgrade head` in the build
   command so a missing migration fails loudly.
3. **Durable object storage.** Either attach a Render persistent disk and point
   `DLG_STORAGE_ROOT` at it (no code change, pins you to one instance), or
   implement an S3 `ObjectStore` behind the existing Protocol
   (`apps/api/app/ingestion/storage.py`).
4. **A real job queue** if you need more than one instance — see
   `apps/api/app/jobs/runner.py` for exactly what changes.
5. **The deployment concerns listed in [SECURITY.md](SECURITY.md):** encryption
   at rest, tenant isolation, signed download URLs, rate limiting.

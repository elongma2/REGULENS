# Regulens — Singapore cosmetic formulation-screening MVP

Regulens is an initial screening assistant for Singapore cosmetic formulations. Its interface uses a restrained inspection-lens mark and the subtitle **Regulatory Intelligence**. Regulatory findings are produced from structured, source-traceable rules and reviewed by a professional. The project does not make product-level approval or compliance determinations.

The current implementation includes the offline regulatory-data pipeline, a separate EU common-ingredient identity catalogue, and a read-only screening core. The accepted regulatory layer covers ACD Appendix I, Annexes II/III/IV/VI/VII, Singapore Regulation 6, and Singapore Third Schedule Parts I–V. The ACD 2026-1 and Singapore 1 December 2025 sources remain separate snapshots; only the Singapore snapshot controls Singapore screening findings.

The identity catalogue is built from Commission Implementing Decision (EU) 2025/1175. It contains 30,416 searchable identities from 30,418 source rows. Catalogue recognition establishes nomenclature only. An exact catalogue identity is searched against the accepted Parts I–V and corresponding ACD scope; a no-match result remains bounded to those lists and does not establish Singapore permission, safety, unrestricted use, or product compliance.

## Accepted Singapore Parts I–V baseline

The accepted runtime dataset is `acd-2026-1__sg-2025-12-01__parts-i-v-r1`. It preserves the ACD bundle version `2026-1, 22 June 2026`, the Annex VII section version `2025-2, 12 December 2025`, and the Singapore consolidation effective 1 December 2025. Parts III–V were promoted on 19 October 2026 after all 15 added PDF spot checks passed; together with the original checks, the accepted baseline records 35/35 completed checks.

The reviewed pre-promotion candidate remains under `data_pipeline/candidate/` as an audit artifact. Normal local and hosted screening now loads the accepted Parts I–V files under `data_pipeline/processed/`. For a future regulatory update, build and validate a new isolated candidate with:

```powershell
uv run python -m data_pipeline.scripts.candidate_pipeline build
uv run python -m data_pipeline.scripts.candidate_pipeline validate
```

After comparing every required item with the immutable source PDF pages, record the results in the candidate report. Promotion remains guarded: every required check must pass, structural validation must pass, and generated hashes must reproduce before this command can replace accepted files:

```powershell
uv run python -m data_pipeline.scripts.candidate_pipeline promote
```

Do not run promotion merely to test a future candidate. The current candidate already matches the active accepted baseline. The completed verification pack is in [`docs/parts-i-v-verification/`](docs/parts-i-v-verification/README.md), including the 15 cases, rendered source pages, extracted values, and reviewer evidence.

Current accepted coverage:

| Regulatory section | Raw records | Normalized rules | Manual-review rules | Source version |
|---|---:|---:|---:|---|
| ACD Annex II Part 1 | 1,729 | 1,729 | 485 | ACD 2026-1 |
| Singapore Third Schedule Part I | 1,709 | 1,709 | 479 | Effective 1 Dec 2025 |
| ACD Annex III Part 1 | 249 | 288 | 127 | ACD 2026-1 |
| Singapore Third Schedule Part II | 221 | 257 | 88 | Effective 1 Dec 2025 |
| ACD Annex IV Part 1 | 145 | 145 | 145 | ACD 2026-1 |
| Singapore Third Schedule Part III | 145 | 145 | 17 | Effective 1 Dec 2025 |
| ACD Annex VI | 62 | 62 | 24 | ACD 2026-1 |
| Singapore Third Schedule Part IV | 56 | 56 | 11 | Effective 1 Dec 2025 |
| ACD Annex VII | 38 | 38 | 11 | Annex VII 2025-2 within ACD bundle 2026-1 |
| Singapore Third Schedule Part V | 35 | 35 | 2 | Effective 1 Dec 2025 |

The accepted baseline contains 4,464 normalized rules, 4,350 identities, and 2,223 Singapore–ACD cross-references: 871 aligned, 1,294 changed, 49 ACD-only, and 9 ambiguous. Changed entries are compared field by field; material differences trigger professional review and never replace the Singapore rule.

The runtime models now accept confirmed ingredient functions (`colourant`, `preservative`, and `uv_filter`) plus closed product-use facts. Parts I and II remain applicable to every resolved ingredient. Positive-list checks run only for an explicitly source-backed or user-confirmed function. Missing function or product facts produce an incomplete assessment, while an identified substance confirmed for a regulated function but absent from a complete accepted list produces the bounded `regulated_function_not_permitted` finding. Concentration, basis, stage, and applicability comparisons remain exact and conversion-free. Warning requirements are exposed for later label review and are never marked as satisfied by formulation screening.

Run validation and tests from the repository root:

```powershell
uv run python -m data_pipeline.scripts.validate_rules
uv run pytest
```

Build and validate the separate identity catalogue only when intentionally updating its accepted baseline:

```powershell
uv run python -m data_pipeline.identity.eu_common_ingredient_glossary.scripts.pipeline --accept
uv run python -m data_pipeline.identity.eu_common_ingredient_glossary.scripts.validate_catalogue
```

Normal API startup never runs this command or rewrites either accepted baseline.

The earlier EU-to-Singapore linkage pipeline and its immutable artifacts remain in the repository for audit history, but they are inactive in the current screening path. Missing linkage decisions no longer create review findings or block catalogue-recognised ingredients.

Start the screening API from the repository root:

```powershell
uv run uvicorn backend.app.main:app --reload
```

In a second terminal, start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development proxy strips `/api`, so `/api/screen-formulation`, `/api/screen-formulation/report`, `/api/screening-options`, `/api/ingredients`, and `/api/acd-ingredients` reach the corresponding backend routes. Set `VITE_API_BASE_URL` to the backend origin, such as `http://127.0.0.1:8000`, when bypassing that proxy.

## Persistent private case workspaces

Regulens uses Supabase Auth, Postgres, and private Storage for pilot workspaces. A user receives one owner organisation at signup. Cases belong to an organisation; each upload creates the next formulation version; clarification state and the complete Agent view are persisted; every screening creates a new immutable result snapshot recording the accepted regulatory dataset version. The database is the source of truth, so a formulation can be reopened after a refresh, sign-out, backend restart, or Vercel cold start without re-uploading or reinterpreting it.

Start a local Supabase stack from the repository root with the [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started):

```powershell
supabase start
supabase db reset
supabase status
```

`supabase db reset` applies the version-controlled migrations under `supabase/migrations/`, including the private `formulation-files` bucket, signup trigger, database functions, and RLS policies. Copy the local API URL, publishable key, and service-role key reported by `supabase status` into an ignored root `.env`, using [`.env.example`](.env.example). Copy only the URL and publishable key into `frontend/.env.local`, using [`frontend/.env.example`](frontend/.env.example). The service-role key is backend-only and must never use a `VITE_` prefix.

Then start FastAPI and Vite with the commands above. Local email confirmations are available in the local mail viewer shown by `supabase status`. Run the isolated database policy tests with:

```powershell
supabase test db
```

The persistent API surface is:

- `GET /me`
- `GET|POST /cases`
- `GET|PATCH|DELETE /cases/{case_id}`
- `GET|POST /cases/{case_id}/formulations`
- `GET|PATCH /formulations/{formulation_version_id}`
- `POST /formulations/{formulation_version_id}/interpret`
- `POST /formulations/{formulation_version_id}/answers`
- `POST /formulations/{formulation_version_id}/prepare`
- `POST /formulations/{formulation_version_id}/screen`
- `GET /formulations/{formulation_version_id}/screenings`
- `GET /screenings/{screening_run_id}`
- `GET /screenings/{screening_run_id}/report.pdf`
- `GET /formulations/{formulation_version_id}/file`
- `GET /cases/{case_id}/review-overview`
- `GET /formulations/{formulation_version_id}/review-workspace?screening_run_id=...`
- `PATCH /review-items/{review_item_id}`
- `POST /cases/{case_id}/review-notes`
- `POST /cases/{case_id}/follow-ups`
- `PATCH /follow-ups/{follow_up_id}`

All domain routes require `Authorization: Bearer <Supabase access token>`. In a configured deployment, `/screen-formulation` is also authenticated and remains the non-persisted New Screen scratch workflow. Regulatory options, searches, evidence, and `/health` remain public. The backend derives the user from the bearer token, uses a server-only service-role client, and repeats membership checks before every trusted database or Storage operation. RLS separately scopes browser-accessible records and private Storage objects through organisation membership. Inaccessible resources return 404.

Completed results can be downloaded as traceable PDF reports. `POST /screen-formulation/report` deterministically re-screens the submitted scratch formulation and returns a PDF, while `GET /screenings/{screening_run_id}/report.pdf` renders the immutable saved result snapshot after the usual organisation access check.

The pilot schema intentionally keeps the established Pydantic payloads as JSONB:

| Table | Purpose |
| --- | --- |
| `profiles` | Auth user display profile |
| `organisations` / `organisation_members` | Workspace ownership and future multi-member support |
| `cases` | One private product or client case |
| `formulation_versions` | Numbered upload, private file path, extraction, Agent state, canonical request, status, and optimistic revision |
| `clarifications` | Stable question keys and unresolved/resolved state projected from the Agent state |
| `screening_runs` | Immutable request/result snapshots plus jurisdiction and accepted dataset version |
| `review_items` | Human workflow status for one result in one immutable screening run |
| `reviewer_notes` | Append-only, attributable notes linked to a case, formulation, clarification, or review item |
| `follow_up_actions` | Open or resolved reviewer actions linked to the same reusable review targets |

Foreign keys cascade from cases through versions, clarifications, screening runs, and professional-review records. Case deletion first removes the corresponding private Storage objects, then deletes the case and related database records. Uploaded regulatory source datasets are never stored in the user-file bucket.

Professional review remains separate from regulatory evaluation. Each saved screening creates a fresh set of review items in the same database transaction. Findings that need attention start at **Not reviewed** and can move through **In review**, **Awaiting information**, and **Reviewed**. This status never edits the stored finding or implies approval or compliance. Notes are append-only; follow-ups can be edited, resolved, and reopened. Earlier screening runs keep their original findings, notes, status, and actions when a formulation is screened again. The formulation workspace lets reviewers filter findings, add contextual notes and follow-ups, and inspect a historical screening run with its matching review state. The case page summarises the latest run, outstanding clarifications, open actions, note count, and recent human activity.

`supabase db reset` for local development or `supabase db push` for a linked hosted project applies both the persistent-case migration and the professional-review migration. The latter backfills review items for existing screening snapshots without inventing notes or completed statuses. Run `supabase test db` against the local Supabase stack to verify table policies, cross-organisation isolation, append-only notes, immutable engine fields, and private Storage access.

Process-local Agent sessions created before this migration have no durable source and cannot be imported. Persistence begins with formulations uploaded into a case after the migration is applied.

## Vercel deployment setup

Create **two Vercel projects from this same repository**. Do not put an OpenAI key in the frontend project and never create a `VITE_*` OpenAI variable.

### Backend project

Use these Vercel project settings:

- Root Directory: repository root (`.`; leave the dashboard field empty when the imported repository root is already selected)
- Framework Preset: **FastAPI** (automatic detection is also valid)
- Build Command: leave empty
- Output Directory: leave empty
- Install Command: leave empty; Vercel reads `pyproject.toml` and `uv.lock`

`pyproject.toml` points Vercel directly to `backend.app.main:app`; it does not create a second FastAPI application. The root [`vercel.json`](vercel.json) enables Fluid Compute and gives the function a 300-second ceiling for bounded Agent requests. Function-level `includeFiles` and `excludeFiles` are intentionally omitted for compatibility with the current FastAPI project configuration; the initial deployment therefore uses Vercel's normal Python project bundle. Repository and local build clutter remain covered by `.gitignore`.

Set these variables on the **backend project** for Production, and separately for Preview if preview deployments need the Agent:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<public-publishable-key>
SUPABASE_SERVICE_ROLE_KEY=<server-only-secret>
OPENAI_API_KEY=<server-side secret>
OPENAI_AGENT_MODEL=gpt-5.6-sol
OPENAI_AGENT_TIMEOUT_SECONDS=180
OPENAI_EXPLANATION_MODEL=gpt-5.6-luna
FRONTEND_ORIGIN=https://<frontend-project-domain>
```

`FRONTEND_ORIGIN` must be an exact HTTP(S) origin without a path. Multiple exact origins may be comma-separated when a stable preview domain is also required. Regulens always retains `http://localhost:5173` and `http://127.0.0.1:5173` for local development; it does not use wildcard CORS. Production reads Vercel environment variables because no `.env` file is committed. Local startup continues to load the ignored repository-root `.env` with operating-system variables taking precedence.

### Frontend project

Use these Vercel project settings:

- Root Directory: `frontend`
- Framework Preset: **Vite**
- Build Command: `npm run build`
- Output Directory: `dist`
- Install Command: `npm install` (or leave the detected default)

Set this public build-time variable on the **frontend project**:

```text
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<public-publishable-key>
VITE_API_BASE_URL=https://<backend-project-domain>
```

Use the backend origin without a trailing route, for example `https://regulens-api.vercel.app`. The browser will then call `https://regulens-api.vercel.app/screen-formulation` and the other existing FastAPI paths. When this variable is absent locally, the frontend continues to use `/api` through the Vite proxy.

After both projects are deployed, update the backend `FRONTEND_ORIGIN` to the final frontend production origin and redeploy the backend if Vercel requests it. Smoke-test:

```text
GET https://<backend-project-domain>/health
GET https://<backend-project-domain>/screening-options
GET https://<frontend-project-domain>/
```

`/health` reports baseline/catalogue availability, configured model names, and whether persistence and the Agent key are configured; it never returns either secret. Sign up through the frontend, confirm the email, create a case, upload a formulation, answer one clarification, screen it, sign out, and verify the saved version and screening after signing in again. Repeat with a second account and confirm it cannot open the first account's URLs.

Before deploying application code, link the repository to the production Supabase project and apply migrations:

```powershell
supabase login
supabase link --project-ref <project-ref>
supabase db push --dry-run
supabase db push
```

In the Supabase Dashboard, keep Email/Password enabled, require email confirmation, set the Site URL to the production frontend origin, and add the localhost and Vercel production/preview callback origins under Auth URL Configuration. Those project credentials and URL allowlists are environment-specific and are the only required setup that is not represented by migrations.

## Formulation Agent

The Agent workspace inside each formulation version accepts CSV, TSV, TXT, XLSX, XLS, JSON, and text-based PDF formulations, interprets the extracted grid into the existing canonical formulation request, and pauses for explicit confirmation before screening. The backend loads the repository-root `.env` once with exported operating-system variables taking precedence. Configure the official OpenAI Python SDK with:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_AGENT_MODEL=gpt-5.6-sol
OPENAI_AGENT_TIMEOUT_SECONDS=180
OPENAI_EXPLANATION_MODEL=gpt-5.6-luna
```

`OPENAI_AGENT_MODEL` defaults to `gpt-5.6-sol`. The legacy `OPENAI_MODEL` remains an Agent-only fallback. `OPENAI_AGENT_TIMEOUT_SECONDS` defaults to 180 seconds and accepts 30–240 seconds; this gives larger structured Sol responses time to finish before the application starts a fresh attempt while remaining below the 300-second Vercel function ceiling. `OPENAI_EXPLANATION_MODEL` defaults independently to `gpt-5.6-luna`. If the key or Agent model is unavailable, the persisted parsed state is retained and the Agent page offers Retry; New Screen and established deterministic screening remain usable. Startup logs report only whether OpenAI and Supabase are configured, the request timeout, and the two selected model names; keys are never logged.

The authenticated compatibility Agent API is:

- `POST /agent/formulations` — multipart formulation-file upload and interpretation; persistent deployments also require a `case_id` form field;
- `GET /agent/formulations/{session_id}` — current structured session;
- `POST /agent/formulations/{session_id}/answers` — typed confirmations and edits;
- `POST /agent/formulations/{session_id}/prepare` — canonical request validation without screening;
- `POST /agent/formulations/{session_id}/retry` — retry a recoverable interpretation failure.

All formulation files are limited to 2 MiB, 500 logical rows, 50 columns, and 8,192 characters per cell. CSV, TSV, and TXT input supports UTF-8, UTF-8 with BOM, and BOM-identified UTF-16 text. XLSX and XLS currently read the first worksheet's displayed values. JSON must be an array of row arrays or an object with a `rows` array. PDF support extracts embedded text locally and does not perform OCR, so scanned/image-only PDFs return an empty-input error. Persistent case uploads store the original bytes in the private Supabase bucket and save the bounded extraction and full Agent state in Postgres. The in-process Agent object is only a request-local working cache reconstructed from those records. Local code only extracts a bounded grid and preserves exact numbered cells; it does not assume the first row is a header or that a particular column name or order is required. The complete bounded grid is sent to the Responses API with response storage disabled; accepted regulatory PDFs, regulatory databases, filesystem paths, and API keys are never included.

Clarifications identify the affected source row, ingredient, field, and original value. The editable interpretation row and its clarification card share the same backend row state: text edits save on blur, selectors save immediately, and resolving either surface updates the other. Missing concentration units are handled per row. An unchanged unmatched identity is shown as unresolved instead of being presented as a recommendation; only an exact accepted catalogue candidate is labelled as a source-backed match.

The Agent model identifies headers, formulation rows, column meanings, explicit formulation metadata, and logical ingredients. A logical ingredient may cite exact cells from more than one source row. Every proposed field retains its cell references, and the backend rejects missing rows, impossible coordinates, changed source values, duplicate logical IDs, or ungrounded values. One bounded semantic repair is allowed before the session fails recoverably. Non-exact identity changes, assumed units, non-numeric values such as `QS` or `balance`, and a missing preparation stage remain under user control. **Confirm & Screen** sends the accepted canonical JSON to the existing deterministic `/screen-formulation` endpoint. The model has no screening tool and cannot generate regulatory findings or limits.

The uploaded formulation file has no mandatory table template. The Agent maps arbitrary source columns into the existing canonical request:

- each ingredient requires only `ingredient_name`;
- `cas_number` is optional;
- concentration is optional and, when present, contains `value`, `unit`, nullable `basis`, and `preparation_stage`;
- formulation ID, formulation name, and Product Context are optional formulation-level fields.

Columns such as **RM Name**, trade name, supplier, function, Notes, Remarks, comments, and batch information remain exact source metadata. They are visible in the collapsed Agent provenance view and after screening but are never sent to the deterministic regulatory engine. When both RM/trade name and INCI/common ingredient columns are present, the Agent proposes the INCI/common ingredient column; unclear mappings require confirmation. Notes are never required and cannot generate regulatory conclusions.

Product Context is handled separately from Preparation Stage. An exact source value may be proposed only when it equals an accepted backend option. Ambiguous source text is left unmapped. If the source file has no Product Context, the user must choose an accepted option or explicitly confirm that it is unavailable; the screening engine may then return information missing for a context-dependent rule. A missing Preparation Stage produces a visible global proposal, such as **Finished product**, which is not applied until the user confirms it.

The representative fixtures are [`backend/tests/fixtures/agent_clean.csv`](backend/tests/fixtures/agent_clean.csv) and [`backend/tests/fixtures/agent_messy.csv`](backend/tests/fixtures/agent_messy.csv). The clean file contains only ingredient and concentration columns. The messy file includes optional RM Name and Remarks fields to demonstrate provenance rather than required screening input.

Normal tests mock both model boundaries. Live integration checks require an explicit opt-in even when `.env` contains a key:

```powershell
$env:RUN_OPENAI_INTEGRATION="1"
uv run pytest -m openai_integration backend/tests/test_agent.py backend/tests/test_review_explanations.py -s
```

The live checks print only safe usage metadata: actual model, token counts, tool-call count, detected row numbers, clarification types, and final state. They never print the key or complete confidential formulations.

After deterministic screening, review-required rows may be sent in one bounded batch to the configured explanation model. The request contains only the existing finding, review codes, submitted facts, selected structured rule evidence, identifiers, references, and source versions. It does not contain PDFs or unrelated datasets. The response can only provide short presentation text and exact precomputed submitted/rule fact strings; it has no fields capable of changing a finding or review flag. Unsafe, invalid, timed-out, or unavailable model output is replaced by deterministic plain-language guidance, so OpenAI availability cannot change or suppress the screening result. The exact review codes and explanation source/model remain under **Technical provenance**.

Search the accepted identity catalogue directly:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/ingredients?query=nia&limit=20"
```

Results are ordered by exact, prefix, then contains matches. The endpoint performs no fuzzy matching and returns no regulatory-status field.

The Agent interpretation table stays focused on canonicalisation and confirmation. After **Confirm & Screen**, the shared evidence drawer can load the trusted EU glossary row from `GET /identity-source-evidence/{raw_record_id}` and the complete accepted page from `GET /identity-source-evidence/{raw_record_id}/page`. Both routes resolve the page and coordinates internally from the accepted catalogue; client-supplied paths or coordinates are never used. This evidence confirms nomenclature only. Singapore regulatory evidence remains part of the deterministic screening result.

Search accepted ACD Annex II/III regulatory records separately:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/acd-ingredients?query=hydro&limit=20"
```

`/ingredients` searches recognised cosmetic names in the EU identity catalogue. `/acd-ingredients` searches active accepted regulatory records in ACD Annex II Part 1 and Annex III Part 1. Neither search endpoint creates a screening finding; Singapore remains the decision source when a Singapore rule is found.

The formulation ingredient picker can query either source or both. **EU glossary** suggestions are labelled as recognised ingredient names; **ACD regulatory lists** suggestions are labelled with their annex and reference. Only enabled sources are requested, stale searches are cancelled, and at most 20 combined suggestions are rendered. EU prefix lookup uses a sorted index and binary search; deterministic contains matching is a bounded fallback.

Runtime matching is exact and conservative. One additional search identity is derived only when an accepted regulatory source name contains the literal delimiter `" (except "`; the prefix may then be searched while the complete accepted wording remains unchanged. No general parenthetical stripping, synonym generation, or fuzzy matching is performed.

Normal runtime loading never runs extraction or rewrites an accepted baseline. `load_accepted_store()` verifies the regulatory baseline and `load_accepted_ingredient_catalog()` independently verifies the identity baseline. If the identity catalogue is unavailable, established regulatory identities still screen normally; catalogue-dependent identity verification is withheld for review. See [the formulation API](docs/FORMULATION_API.md), [the runtime examples](docs/RUNTIME_SCREENING_EXAMPLES.md), [the professional review pack](docs/REGULATORY_PROFESSIONAL_REVIEW_PACK.md), and [the regulatory pipeline notes](docs/REGULATORY_DATA_PIPELINE.md).

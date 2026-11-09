# Regulens Intelligent Multi-Document and Trade-Name Composition Implementation Plan

## 1. Purpose and architectural boundary

This plan extends the existing case-based formulation workflow so Regulens can accept a finished-product formulation, ingredient list, supplier composition statement, SDS/MSDS, or a combination of those documents through one upload experience.

It also adds an organisation-private **saved SDS/MSDS library** as a required part of the formulation-checking workflow. After a supplier document has been uploaded, processed and confirmed once, Regulens remembers the original private file, its exact revision, the confirmed extraction and its source-page evidence. A reviewer preparing a later formulation can attach that saved document from Regulens instead of locating and uploading it again. Compatible saved extractions are reused without another parser or AI call; formulation-specific facts such as the raw-material usage percentage are still confirmed for each formulation.

The implementation must preserve the current regulatory authority boundary:

- AI may classify documents and extract source-backed facts.
- Deterministic code validates concentration expressions, resolves document relationships only when evidence is sufficient, performs concentration arithmetic, aggregates verified identities, and invokes the existing Singapore Parts I-V screening engine.
- AI must not perform arithmetic, create chemical identities, infer undisclosed ingredients, or decide regulatory findings.
- A trade-name parent is a commercial raw material, not an ingredient to screen alongside its constituents.
- Incomplete or unresolved assembly must remain visible and must never produce unsupported clearance.

The target flow is:

```text
One unified upload
  or attach a previously processed SDS/MSDS from the private library
  -> per-document parsing and classification
  -> schema-specific, source-backed extraction
  -> user-confirmed document/material relationships
  -> deterministic constituent calculation and aggregation
  -> existing canonical FormulationRequest
  -> existing Singapore Parts I-V screening
  -> existing findings, evidence, notes and review workflow
```

This is an incremental extension. It does not create another regulatory engine or replace historical screening snapshots.

---

## 2. Evidence from the four pilot documents

The four supplied documents demonstrate why filename-based classification and a single flat ingredient schema are insufficient.

| Sample | Observed structure | Required interpretation | Current compatibility |
|---|---|---|---|
| OPTASENSE RMA-IS-SS-(SG), code EN80159 | Supplier percentage-composition statement. Each INCI is assigned an FDA letter code. The same page defines `A >75%`, `B 50-75%`, `C 25-50%`, `D 10-25%`, `E 5-10%`, `F 1-5%`, `G 0.1-1%`, `H <0.1%`. | Extract the material name, product code, constituent names, reported code, and the document-local legend. Resolve each code deterministically to a structured interval while retaining the code and legend evidence. | Selectable text is available, but there is no legend model or raw-material/constituent hierarchy. |
| VISCOPTIMA SE-LQ-(RB), code EN00297 | Supplier composition statement with explicit lower limit, upper limit and percent unit for each INCI. | Preserve each range exactly. Do not normalise the independently stated ranges to total 100%. | The current range model can represent the values, but it would incorrectly treat them as finished-product concentrations unless the document role and parent material are modelled. |
| MATRIXYL 3000 MBAL, item code SE28264 | Supplier product information with approximate values, `qsp 100`, `max. 1`, CAS values and a manufacturing-additive row. | Represent approximate, maximum and remainder-to-total semantics separately. `qsp 100` must not become an exact 100% constituent. Preserve role labels such as manufacturing additive. | Approximate and upper-bound values exist. `qsp 100`, parent material and constituent roles do not. |
| SiCare 2315F3 MSDS | Six-page image-based MSDS. Page 1 contains product and supplier identity. Page 2, Section 3, lists six chemicals with CAS numbers and w/w ranges. | Detect an SDS/MSDS role and a composition-bearing section. Keep safety statements out of formulation fields. Extract the page-2 composition table with page evidence. | Reverified on 7 November 2026 with the repository's actual `parse_formulation_upload()` path in `backend/app/services/agent_csv.py`. `pypdf.PdfReader.extract_text(extraction_mode="layout")` produced no usable rows and the parser returned HTTP 422 / `agent_pdf_text_unavailable`. A bounded OCR/vision fallback is therefore required for this exact sample. |

Important source-handling rules derived from the samples:

1. A percentage in a supplier statement describes the composition of the supplier material, not the finished cosmetic product.
2. A legend belongs only to the document and revision that defines it. Codes must never be resolved using a global assumed legend.
3. Range endpoints and operators must be preserved. If inclusivity is not stated, it remains unspecified.
4. `qsp 100` means remainder to the stated total. It does not mean the named constituent is present at exactly 100%.
5. Supplier ranges may overlap or have totals above 100 when considered independently. Regulens must not silently renormalise them.
6. SDS Section 3 may be incomplete by design. A successful extraction is not proof of complete formulation disclosure.

The SiCare result above is a file-specific parser observation, not an assumption that every SDS or every SiCare revision is scanned. Every PDF first uses the existing local text parser; OCR/vision is invoked only when that deterministic extraction returns no usable content or when the extracted layout is demonstrably insufficient.

---

## 3. Existing architecture audit

### 3.1 Upload and parsing

The current upload parser is `backend/app/services/agent_csv.py`.

- `parse_formulation_upload()` accepts CSV, TSV, TXT, XLSX, XLS, JSON and PDF.
- The per-file limit is 2 MiB, with 500 rows, 50 columns and 50 PDF pages.
- XLSX and XLS expose every non-empty worksheet to interpretation and retain worksheet labels in source rows.
- PDFs use `pypdf.PdfReader` and turn every non-empty extracted text line into a one-column `ParsedCSV` row.
- PDF rows retain `row_pages` and `row_snippets`.
- There is no OCR fallback.
- There is no layout/table object, document-level identity, document classification, or multi-file batch.

The persistent case upload route is `backend/app/routes/cases.py::upload_formulation()`.

- It accepts one `UploadFile`.
- It uploads that file to private Supabase Storage.
- It creates one `formulation_versions` row.
- It synchronously invokes the formulation Agent.
- If interpretation fails, the source file and recoverable failed state are retained.

The scratch compatibility route in `backend/app/routes/agent.py` is also single-file and process-local.

The frontend file inputs in `frontend/src/pages/CasePage.tsx` and `frontend/src/pages/AgentPage.tsx` do not have the `multiple` attribute and call one-file API methods.

### 3.2 AI interpretation

The current implementation is in `backend/app/services/formulation_agent.py`.

- `_parsed_document_payload()` serialises the complete bounded grid/line set with page metadata.
- `OpenAIFormulationInterpreter` uses the Responses API with `store=False`, strict structured output and read-only catalogue/regulatory search tools.
- `ModelInterpretation` contains one table interpretation, formulation metadata, ingredient rows and a limited multiple-product assessment.
- Trade-name, supplier and raw-material columns are mapped as metadata rather than modelled entities.
- The prompt deliberately prefers explicit INCI/common names over trade names and prevents hazard/safety statements from becoming ingredients.
- Structured-output correction and source-reference repair occur inside one top-level attempt.
- `FormulationAgentService` permits three top-level attempts with bounded backoff and records token/tool diagnostics.
- The default interpretation model is configured by `OPENAI_AGENT_MODEL` and currently falls back to `gpt-5.6-sol`.
- The lower-cost explanation role is configured separately by `OPENAI_EXPLANATION_MODEL` and currently falls back to `gpt-5.6-luna`.

This architecture provides strong provenance validation, but every supported upload currently enters the same relatively expensive interpretation path. It has no cheap deterministic structured-file fast path and no document-role-specific extraction schema.

### 3.3 Canonical formulation and confirmation

The current canonical input in `backend/app/models/formulation.py` is flat:

```text
FormulationRequest
  ingredients[]
    name
    cas_number
    concentration
    regulated_functions[]
```

`FormulationConcentration` supports exact, range, upper bound, lower bound, approximate and unknown quantities, with units, basis and preparation stage. It does not distinguish:

- percentage inside a supplier raw material;
- percentage of that raw material used in the finished product;
- calculated contribution to the finished product;
- document-local coded ranges;
- remainder-to-total (`qsp`) composition.

`AgentSessionView` and `AgentIngredientRow` in `backend/app/models/agent.py` preserve source cells/pages, source values, edits, uncertainties and canonical preparation state. The current Agent UI in `frontend/src/pages/AgentPage.tsx` supports row-level correction, ranges, bounds, CAS, units, functions, adding/removing ingredients and source snippets. It does not have parent raw-material rows, attached supplier documents, constituent expansion, usage percentages or calculation provenance.

### 3.4 Identity and regulatory screening

The existing reusable path is correct for the new workflow:

- `backend/app/services/resolver.py` resolves supported identities conservatively.
- `backend/app/services/formulation.py` assembles formulation-level regulatory context.
- `backend/app/services/compliance.py` evaluates deterministic Singapore rules.
- `backend/app/services/evidence.py` builds traceable evidence.
- `backend/app/routes/cases.py::screen_persistent_formulation()` loads the saved canonical `FormulationRequest`, runs the deterministic engine and inserts an immutable screening run.

The new architecture should derive a flat, confirmed `FormulationRequest` from the material/constituent assembly and then call this path unchanged. The raw trade-name parent must not be included as an additional screening ingredient.

### 3.5 Persistence, storage and security

The current Supabase design provides a strong base:

- `formulation_versions.raw_extraction` stores parsed source input.
- `formulation_versions.agent_state` stores interpreted/editable workflow state.
- `formulation_versions.canonical_formulation` stores the prepared flat request.
- Original files are stored privately under organisation/case/version paths.
- `SupabaseGateway` explicitly checks membership even though service-role operations bypass RLS.
- Screening runs are immutable snapshots with dataset versioning.
- Optimistic revision checks protect Agent updates.
- Deletion removes private files before database records.

The missing persistence concept is more than one source document per formulation version, including independent processing status, extraction result and association state.

### 3.6 Performance and recovery

Current interpretation is synchronous. There is no durable queue or worker. The persistent upload route stores the source before model interpretation, so failures are recoverable, but a multi-document request would risk exceeding serverless duration if it processed every file sequentially in one request.

The process-local Agent cache is optional; the database remains the persistent source of truth. There is no extraction cache keyed by file hash/schema version, and there is no per-document retry status.

---

## 4. Recommended minimal architecture

### 4.1 Keep one formulation version, add many documents

One `formulation_version` remains the product revision being assembled and screened. Each version may contain one or more `formulation_documents`. Confirmed SDS/MSDS and supplier-composition documents are also retained in an organisation-private supplier-document library so the same exact revision can be attached to future formulation versions without re-uploading or re-running unchanged extraction.

#### 4.1.1 Remember processed SDS/MSDS documents for future formulations

The saved supplier-document library is a required product feature, not merely a processing cache.

Primary user story:

> As a regulatory reviewer, after I upload and confirm an SDS/MSDS for a supplier raw material once, I can select that saved document in a later formulation case without finding or uploading the file again. Regulens restores the reviewed composition, exact document revision and source-page evidence, then asks only for formulation-specific information such as how much of that raw material is used.

Repeat formulation-checking example:

1. In **Case A**, the reviewer uploads an SDS for `Supplier Blend X`, confirms the extracted constituents and completes the formulation check.
2. Regulens stores that SDS as an organisation-private saved supplier document, independently of Case A, while Case A remains pinned to the exact revision it used.
3. Weeks later, in **Case B**, the reviewer selects **Add saved SDS or supplier document**, searches for `Supplier Blend X` and attaches the saved revision without having the local PDF.
4. Regulens restores the reviewed constituent extraction and page evidence immediately when its extraction version is still compatible. It asks for Case B's raw-material usage and any formulation-specific relationship or correction, then recalculates finished-product contributions.
5. If the supplier has issued a revised SDS, the reviewer uploads it as a new revision. Case A and any earlier screening runs continue to reference the older revision; Case B uses the newer revision only when the reviewer explicitly selects it.

This reuse must survive page refresh, sign-out/sign-in, backend restart and navigation between cases. It is persistent workspace data, not browser state and not a process-local cache.

User-facing behaviour:

1. When a user uploads an SDS/MSDS or supplier composition document for a formulation, Regulens processes it normally and asks for any required role, material or extraction confirmation.
2. After that document is confirmed, Regulens remembers the exact document revision inside the user's organisation-private workspace. The saved record includes the original private file, SHA-256 hash, supplier/trade name, product code, revision/date where available, source-backed extraction, processing version and provenance.
3. A later formulation upload offers **Add saved supplier document**. The user can search and attach the previously processed SDS/MSDS without choosing the local file again.
4. When the stored extraction is compatible with the current extraction schema and model configuration, attaching it makes no parser or AI call. Regulens creates a formulation-local snapshot and proceeds directly to relationship confirmation, material usage and deterministic concentration calculation.
5. If extraction logic has changed, Regulens reprocesses the already stored private file. The user is not asked to upload it again, and existing formulation snapshots and screening runs remain unchanged.
6. Uploading the exact same bytes again in the same organisation is detected by SHA-256 and transparently reuses the saved document rather than storing or interpreting a duplicate.
7. A revised supplier document is a new immutable library revision. Regulens must not silently replace the revision already attached to an older formulation.

Visible save-and-reuse confirmation:

- After the first successful confirmation, show **Saved for future formulations** with the supplier/trade name, product code and revision when available. This makes the persistent behaviour explicit rather than presenting it as an invisible cache.
- Provide a **View saved supplier documents** action from the formulation workspace so the reviewer can confirm that the SDS/MSDS is available for later use.
- On a later formulation, **Add saved SDS or supplier document** opens the organisation-private library first. The reviewer can search by supplier, trade name, product code, filename or revision, inspect the source metadata, and attach the exact revision.
- Reusing a saved document must not require the original local file and must not repeat a compatible parser or AI interpretation call.
- The attachment screen must clearly separate **remembered document facts** from **facts required for this formulation**. In particular, the raw-material usage percentage is never copied from a previous formulation unless it is explicitly present in the new finished-product formulation and confirmed by the reviewer.
- If no saved document matches, the same control offers **Upload new SDS or supplier document** and processes it through the normal confirmation flow.
- Users may archive an obsolete library revision so it no longer appears in new searches. Existing formulations and immutable screening results remain pinned to the revision they used.

This feature remembers the supplier document and its verified extraction; it does not assume that the same raw-material usage percentage applies to every formulation. Finished-product usage remains formulation-specific and must be entered or confirmed for each formulation before calculated constituent concentrations can be screened.

What is remembered and what must be supplied again:

| Reused from the saved SDS/MSDS | Confirmed for each new formulation |
|---|---|
| Original private file and exact SHA-256 | Whether this exact document revision applies to the selected raw material |
| Supplier, trade name, product code and document revision when source-backed | Raw-material usage in the finished product |
| Confirmed document role and governing composition section | Any formulation-specific association when several materials/documents are present |
| Extracted constituents, CAS values, ranges, legends and source pages | Corrections that apply only to this formulation version |
| Extraction schema/model version and safe diagnostics | Product context and other facts required by the existing screening workflow |

The picker must label this action **Add saved SDS or supplier document**. It appears inside the existing formulation workspace and is optional: a reviewer can still upload a new document or continue with an ordinary INCI-only formulation. Selecting a saved document must show its supplier/trade name, product code, revision/date, filename and processing status before attachment so similarly named revisions are not confused.

Successful attachment must not display a new upload or AI-processing spinner when the stored extraction is compatible. Instead, it should immediately show the restored constituent data and provenance for review. If reprocessing is required because the extraction schema changed, the UI must say that Regulens is reprocessing the saved private file and must not ask the user to upload it again.

Privacy and trust boundary:

- Saved documents are visible only to authorised members of the same organisation.
- No public or cross-organisation supplier-document catalogue is created.
- Search results must never reveal another organisation's filenames, hashes, suppliers, trade names or document existence.
- Reuse always records the exact saved document revision and source pages used by the current formulation.
- Removing one formulation detaches its link but does not delete the remembered SDS/MSDS. Archiving hides a saved document from future selection while preserving historical references.

```text
Organisation
  Saved Supplier Documents[]
    original private file
    supplier/trade name/product code/revision
    parsed content + source-backed extraction
    processing/extraction version
    usage links[]

Case
  Formulation Version
    Documents[]
      uploaded formulation-scoped document, or
      attachment to one saved supplier-document revision
      formulation-local classification/association confirmation
    Assembly State
      direct ingredients[]
      trade materials[]
        usage in finished product
        documents[]
        constituents[]
      unresolved associations[]
    Calculation Snapshot
      constituent contributions[]
      aggregated ingredients[]
    Canonical FormulationRequest
    Immutable Screening Runs[]
```

This preserves the existing version and screening model while adding an organisation-scoped reusable supplier-document record plus formulation-local document attachments. Reuse is private to one organisation; Regulens does not create a public or cross-customer supplier-document catalogue.

### 4.2 Database migration

Add `supplier_documents` for reusable organisation-private SDS/MSDS and supplier-composition sources:

| Column | Purpose |
|---|---|
| `id uuid primary key` | Stable reusable document ID. |
| `organisation_id uuid` | RLS and backend membership boundary. |
| `original_filename text` | Display and audit. |
| `storage_path text` | One private Storage object retained independently of a case. |
| `mime_type text`, `sha256 text`, `page_count integer nullable` | Input metadata and organisation-scoped exact duplicate detection. |
| `supplier_name`, `trade_name`, `product_code` | Source-backed searchable library metadata; nullable when absent. |
| `document_revision_label`, `document_date` | Supplier-stated revision information; never invented from upload time. |
| `supersedes_supplier_document_id uuid nullable` | Explicit or reviewer-confirmed revision lineage. |
| `detected_roles`, `confirmed_roles` | Source-backed role evidence; only confirmed SDS/MSDS or supplier-composition documents appear in the reuse picker. |
| `parsed_content jsonb`, `extraction_result jsonb` | Reusable bounded source content and source-backed extraction. |
| `extraction_schema_version`, `model_configuration` | Determines whether extraction can be reused without reprocessing. |
| `processing_status`, `processing_diagnostics`, `error` | Same recoverable processing contract used by formulation documents. |
| `processing_key`, `processor_run_id`, `processing_started_at`, `heartbeat_at`, `lease_expires_at`, `processing_attempt` | Idempotency and interrupted-request recovery. |
| `library_status text` | `processing`, `available`, `needs_confirmation`, `archived`, or `failed`. |
| `revision integer`, `created_by`, `created_at`, `updated_at` | Optimistic concurrency and attribution. |

Add `formulation_documents` as the formulation-local attachment/snapshot:

| Column | Purpose |
|---|---|
| `id uuid primary key` | Stable document ID. |
| `formulation_version_id uuid` | Cascades with formulation version. |
| `supplier_document_id uuid nullable` | Exact saved supplier-document revision when reused. |
| `original_filename text` | Display and audit. |
| `storage_path text nullable` | Private version-scoped object for ordinary formulation files; reusable supplier documents use the library object's path. |
| `mime_type text` | Input metadata. |
| `sha256 text` | Duplicate detection and organisation-scoped extraction cache key. |
| `page_count integer nullable` | PDF metadata. |
| `processing_status text` | `uploaded`, `parsing`, `classifying`, `extracting`, `needs_confirmation`, `ready`, `interrupted`, `failed`. |
| `detected_roles jsonb` | Role candidates, confidence and evidence. A document may have multiple roles/sections. |
| `confirmed_roles jsonb nullable` | Reviewer-confirmed document roles. |
| `parsed_content jsonb nullable` | Bounded text/layout/OCR lines with page evidence. |
| `extraction_result jsonb nullable` | Schema-specific source-backed extraction. |
| `processing_diagnostics jsonb nullable` | Safe model/usage/attempt metadata. |
| `error jsonb nullable` | Recoverable document error. |
| `processing_key text nullable` | Idempotency key derived from document hash, extraction schema and model configuration. |
| `processor_run_id uuid nullable` | Identifies the current processing lease. |
| `processing_started_at`, `heartbeat_at`, `lease_expires_at` | Interrupted-request and stale-run recovery. |
| `processing_attempt integer` | Monotonic attempt number for safe diagnostics and retries. |
| `supersedes_document_id uuid nullable` | Formulation-local source relationship; reusable supplier revision lineage lives on `supplier_documents`. |
| `document_revision_label text nullable` | Supplier-stated revision/version preserved verbatim. |
| `governing_for_material boolean` | Reviewer-confirmed source selection; constrained so conflicting revisions cannot both contribute. |
| `attached_extraction_key text nullable` | Exact library extraction version snapshotted for this formulation. |
| `revision integer` | Optimistic document edits. |
| `created_by`, `created_at`, `updated_at` | Attribution. |

Add to `formulation_versions`:

- `assembly_state jsonb`: confirmed material hierarchy, direct ingredients, relationships and unresolved items.
- `assembly_revision integer`: optimistic updates independent of document extraction revisions.
- `calculation_snapshot jsonb`: deterministic, reproducible contributions and aggregate output.

Retain `canonical_formulation` as the derived flat screening input. Do not replace it with raw material records.

Enforce an organisation-scoped exact-file uniqueness rule on `supplier_documents(organisation_id, sha256)` and a formulation attachment uniqueness rule on `(formulation_version_id, supplier_document_id)`. These constraints complement, rather than replace, the contribution-lineage checks used during assembly.

RLS policies must scope `supplier_documents` directly through organisation membership and `formulation_documents` through formulation version -> case -> organisation membership. Backend service-role methods must repeat both checks. Storage paths become:

```text
organisation_id/supplier-documents/supplier_document_id/original_filename
organisation_id/case_id/formulation_version_id/document_id/original_filename
```

For historical versions, expose the existing `source_storage_path` as a legacy document without rewriting immutable screening history. New multi-document versions use `formulation_documents` as canonical. Attaching a saved supplier document copies its selected extraction into the formulation attachment/assembly snapshot; a later library reprocessing or newer supplier revision cannot silently change an existing formulation or immutable screening run.

Deleting a formulation detaches its links but does not delete a reusable supplier document. Archiving a library document hides it from new selection while preserving existing links. Permanent library deletion is blocked while referenced unless the user first detaches it from every formulation; organisation/account deletion removes the private library files and records.

### 4.3 Typed domain models

Add a dedicated module such as `backend/app/models/document_intake.py` with the following concepts.

```text
DocumentRole
  finished_product_formulation
  ingredient_list
  supplier_composition
  sds_msds
  technical_document
  unknown

DocumentRoleEvidence
  role
  confidence
  page
  source_snippet
  reasons[]

SavedSupplierDocument
  supplier_document_id
  organisation_id
  supplier_name / trade_name / product_code
  document_revision_label / document_date
  sha256
  extraction_schema_version / processing_key
  supersedes_supplier_document_id
  library_status

SupplierDocumentAttachment
  formulation_document_id
  supplier_document_id
  attached_extraction_key
  formulation_local_roles
  association / governing confirmation
  attached_at / attached_by

CompositionQuantity
  kind: exact | range | upper_bound | lower_bound | approximate |
        coded_range | remainder_to_total | unknown
  value/lower/upper
  lower_inclusive/upper_inclusive
  unit
  basis
  raw_text
  reported_code
  legend_entry_id

CompositionLegend
  legend_id
  name
  entries[]
    code
    raw_definition
    normalized_quantity
    evidence

SupplierMaterial
  material_id
  trade_name
  supplier_name
  product_code
  finished_product_usage
  attached_document_ids[]
  constituents[]
  disclosure_status
  confirmation_status

MaterialConstituent
  constituent_id
  submitted_name
  cas_number
  composition_quantity
  source_evidence[]
  verified_identity
  role_label
  user_edits

DirectIngredient
  existing ingredient fields
  source_document_id
  source_evidence[]

CalculatedContribution
  source_material_id or direct ingredient ID
  verified_identity_group
  composition_quantity
  material_usage
  finished_product_quantity
  calculation_formula
  source_evidence[]

AggregatedIngredient
  verified_identity_group
  display identity
  aggregate_quantity
  contributions[]
  completeness/status

AssemblyIssue
  issue_id
  code
  severity: error | review_required | warning
  scope: assembly | document | material | constituent | association | calculation
  blocking_for_calculation
  blocking_for_full_evaluation
  document_ids[] / material_ids[] / constituent_ids[]
  evidence[]
  reviewer_action

AssemblyResult
  completeness: complete | partial | blocked
  included_ingredients[]
  unresolved_raw_materials[]
  incomplete_disclosures[]
  unresolved_associations[]
  excluded_items[] with exclusion reason
  issues[]
  evaluated_scope
  calculation_snapshot
```

Do not reuse `FormulationConcentration` for supplier composition percentages. The two quantities have different meanings and should only meet in deterministic calculation code.

`AssemblyIssue.code` is a bounded enum. Initial codes include `unresolved_raw_material`, `incomplete_supplier_disclosure`, `material_usage_missing`, `constituent_concentration_missing`, `constituent_identity_unresolved`, `constituent_identity_ambiguous`, `document_association_unconfirmed`, `duplicate_document`, `composition_statement_conflict`, `missing_legend`, `unknown_legend_code`, `incompatible_quantity_basis`, `impossible_composition_total`, `unverified_identity_aggregation`, and `calculation_withheld`. These records, rather than UI card state, are the source of truth for preparation and screening completeness.

---

## 5. Unified ingestion and document processing

### 5.1 API shape

Extend the authenticated case routes:

```text
POST /cases/{case_id}/formulations
  multipart files[]
  Creates one formulation version and its document records.

POST /formulations/{version_id}/documents
  multipart files[]
  Adds supplier/supporting documents later.

GET /supplier-documents
  Searches the authenticated organisation's saved SDS/MSDS and supplier documents
  by supplier, trade name, product code, revision or filename.

GET /supplier-documents/{supplier_document_id}
GET /supplier-documents/{supplier_document_id}/file
PATCH /supplier-documents/{supplier_document_id}
  Read metadata/download privately, correct source metadata or archive the document.

POST /formulations/{version_id}/documents/attach
  Attaches an exact saved supplier-document revision without uploading the file again.

DELETE /formulations/{version_id}/documents/{document_id}
  Detaches it from this formulation; does not delete the organisation library source.

GET /formulations/{version_id}/documents
GET /formulation-documents/{document_id}

POST /formulation-documents/{document_id}/interpret
POST /formulation-documents/{document_id}/retry

PATCH /formulation-documents/{document_id}
  Confirm/correct roles and extracted document metadata.

PATCH /formulations/{version_id}/assembly
  Confirm associations, material usage, constituents and direct ingredients.

POST /formulations/{version_id}/prepare
  Recalculate and derive the existing canonical FormulationRequest.
```

The existing single-file clients remain compatible by sending a one-element `files[]`. Existing Agent aliases remain until the frontend migration is complete. A newly uploaded document that is confirmed as `sds_msds` or `supplier_composition` is saved to the organisation library automatically; the user does not need a separate "save this SDS" action.

If an uploaded file has the same organisation-scoped SHA-256 as an existing library document, the API returns that document and creates only the new formulation attachment. It does not store or process the binary twice. Filename similarity alone is never sufficient for reuse.

### 5.2 Avoid one long multi-file request

The create route should upload files, create document rows and return quickly. The frontend then starts document interpretation with a concurrency limit of two. Each request processes one document and persists its result.

Benefits:

- one bad document does not fail the batch;
- a serverless timeout cannot erase successfully processed documents;
- retries are per document;
- the user can leave and resume;
- no queue is required for the Tuesday MVP.

A durable background worker can be introduced later if pilot latency or serverless limits require it.

### 5.3 Idempotent processing contract

Every document interpretation request must be safe to repeat after a timeout, browser refresh or server restart.

1. On upload, calculate the file SHA-256 before scheduling interpretation. Within one formulation version, an identical hash returns the existing attachment and does not create a second source or contribution. Across formulation versions in the same organisation, an identical confirmed supplier/SDS hash reuses the saved library binary and compatible extraction while creating a new formulation-local attachment. Cross-organisation hashes are never queried or revealed.
2. Derive `processing_key` from `organisation_id + file_sha256 + extraction_schema_version + model_configuration`. A completed result with the same key is returned without another parse/model call.
3. Acquire processing with an atomic status/revision comparison and a time-bounded lease. Only the matching `processor_run_id` may heartbeat or commit the result.
4. Persist status transitions: `uploaded -> parsing -> classifying -> extracting -> needs_confirmation | ready`; failures use `interrupted` or `failed`, never a misleading empty `ready` state.
5. Commit extraction result, diagnostics and final status atomically. A retry increments `processing_attempt` and replaces no confirmed reviewer edits.
6. A request observing an unexpired lease returns current progress. A lease with no heartbeat past its expiry becomes safely retryable; the stale worker cannot overwrite the later run.
7. `GET` endpoints expose persisted progress so a refreshed frontend hydrates state instead of restarting work. The user can explicitly retry `failed`, `interrupted` or stale documents.
8. Partial batch success is durable. Retrying one document cannot duplicate material, constituent or calculated-contribution records from earlier attempts.
9. Reuse is pinned to an exact supplier-document ID, revision and `attached_extraction_key`. A newer revision or extraction schema is offered explicitly; it never mutates an existing assembly automatically.

### 5.4 Saved supplier-document library lifecycle

The library is an organisation-private convenience and provenance feature, not a global chemical-composition database.

1. A newly uploaded SDS/MSDS or supplier composition is processed normally and attached to the current formulation. Once its role is confirmed, its original private file, source metadata and extraction become available for later reuse automatically.
2. Future upload screens offer `Add saved supplier document`. Search results disclose only documents in the authenticated organisation and show supplier, trade name, product code, revision/date, filename, readiness and last-used date.
3. Selecting a document attaches the exact saved revision and compatible extraction snapshot to the new formulation. The reviewer still confirms which trade material it describes and how much of that material is used in the finished product.
4. Reuse never assumes that a supplier composition is still current. A newer document is stored as a new revision and may be suggested, but the reviewer chooses which revision governs each formulation.
5. If the extraction schema/model configuration has changed, Regulens can reprocess the already stored original file. The user is not asked to upload it again, and existing attachments remain pinned to their prior extraction snapshot.
6. Archiving prevents future selection but preserves existing case provenance. Permanent deletion is allowed only when no formulation attachment references the document.
7. Ordinary formulation files are not automatically presented as reusable supplier documents. Only confirmed SDS/MSDS or supplier-composition roles enter this picker.
8. No document, filename, hash, metadata or extraction is shared across organisations.

---

## 6. Classification strategy and decision rules

Classification must be evidence-based and may return several section roles for one document.

### 6.1 Deterministic signals first

Use headings, table headers, structure and exact phrases as signals, not final conclusions.

| Role | Strong signals | Negative/ambiguity signals |
|---|---|---|
| Finished-product formulation | Product/formula identifier plus material or ingredient rows and a finished-product usage/addition column; totals or explicit finished-product basis. | Supplier composition title, SDS Section 3, no product formulation context. |
| Ingredient list | INCI/chemical identities, possibly CAS, with no supplier-material composition framing and no finished-product usage. | Trade product header with composition limits. |
| Supplier composition | One trade/product name, supplier or item code, constituent INCI/CAS table and composition percentages/codes inside that material. | Multiple formulation materials with finished-product additions. |
| SDS/MSDS | Safety Data Sheet heading, numbered SDS sections, hazard content; composition often under Section 3. | None; it may also contain a supplier-composition section. |
| Technical document | Product-information/specification heading and composition-bearing section, but not enough evidence for a narrower role. | Conflicting sections. |
| Unknown/mixed | Insufficient or contradictory evidence, or several plausible formulations. | Requires confirmation. |

Percentages alone must never determine the role.

### 6.2 Model output

`DocumentClassification` must return:

- one or more proposed roles;
- confidence per role;
- exact page/snippet evidence;
- detected supplier, trade name and product code if explicit;
- possible formulation/material identifiers;
- multiple-product indicator;
- recommended extraction schema;
- questions requiring user confirmation.

If evidence does not establish a role, return `unknown`; do not force a classification.

### 6.3 Cross-document association

Association is a separate, deterministic suggestion stage after extraction.

High-confidence association evidence:

1. exact product code match;
2. exact normalised trade name plus compatible supplier;
3. an explicit reference in the finished-product document to the supplier document/product code;
4. a user-confirmed association.

Weak name similarity may produce a suggestion, never an automatic link. Conflicting supplier, revision or product-code evidence requires confirmation.

When multiple finished-product formulations are detected, the system must ask the user to choose or split them. It must not merge them silently.

When two supplier documents describe the same material:

- preserve both documents and revisions;
- prefer no automatic override;
- compare extracted composition;
- show conflicts and ask which source/revision governs this formulation;
- ensure the same document cannot contribute twice.

### 6.4 Multi-document relationship and revision rules

The assembly layer must retain document identity; it must not flatten all extracted rows into one undifferentiated ingredient list.

- **Multiple ingredient lists:** preserve each list and its evidence. Rows may be combined only after exact verified identity resolution or explicit reviewer confirmation. The same disclosed row from a duplicate document must contribute once.
- **Multiple finished formulations:** one formulation version may have only one active finished-product assembly. If a document contains several products, or a batch contains several finished formulations, require the user to select/split them into separate formulation versions before calculation. Never pool their materials.
- **Duplicate files:** identical SHA-256 within a formulation version is idempotent and reuses the existing document. A duplicate filename with different bytes is not a duplicate and requires review.
- **Conflicting composition statements:** retain every statement, highlight differing identities/ranges/legends, and create `composition_statement_conflict`. Do not average values or choose the least/most restrictive statement automatically.
- **Document revisions:** record explicit revision labels/dates and an optional `supersedes_document_id`. A reviewer selects one governing revision per material and formulation version. Superseded records remain visible for provenance but cannot contribute concurrently.
- **Saved-library revisions:** uploading a changed supplier file creates a new `supplier_documents` record even when supplier/trade/product metadata match. Link revisions only from explicit source metadata or reviewer confirmation. Existing formulations remain pinned to their prior revision; new formulations may choose the latest confirmed revision from the library picker.
- **Double-counting prevention:** calculated contributions have a stable lineage key such as `(assembly_revision, material_id, constituent_id, governing_document_id)`. Preparation rejects duplicate active lineage keys and any material with more than one governing conflicting source.
- **Association conflicts:** exact product codes and supplier/trade-name evidence may suggest a relationship, but incompatible product codes, suppliers or revisions require confirmation. Model confidence never overrides a confirmed relationship.

Changing the governing document invalidates the previous calculation snapshot, increments `assembly_revision`, and requires deterministic recalculation. It does not rewrite an earlier immutable screening run.

---

## 7. Cost-aware AI and extraction pipeline

### 7.1 Processing tiers

| Tier | Input | Model calls | Behavior |
|---|---|---:|---|
| 0 - deterministic | Clear CSV/XLSX headers, JSON, recognised concentration expressions and legends | 0 | Parse, classify and extract using deterministic rules. Validate and ask only genuine clarification questions. |
| 1 - low-cost structured extraction | Selectable-text PDF or ambiguous structured file | Usually 1 per document | Combine classification and schema-specific extraction in one strict-output request. Use document-local source lines/pages. |
| 2 - bounded OCR/vision | Image-only PDF | 1 page-triage call plus 1 extraction call for relevant pages, when possible | Use a low-cost vision-capable model or approved OCR provider. Render bounded pages; identify relevant pages, then extract at adequate resolution. |
| 3 - complex fallback | Failed strict extraction or genuinely mixed/complex document | At most 1 escalation per document | Use the current higher-capability Agent model. Never escalate straightforward documents automatically multiple times. |

Introduce `OPENAI_DOCUMENT_MODEL` for the low-cost structured/vision role and keep `OPENAI_AGENT_MODEL` as the complex fallback. The default should be the existing lower-cost structured-output-capable model after validating that it supports the required text/vision schema. Do not hardcode a provider assumption into domain logic.

### 7.2 Combine calls where safe

For straightforward documents, classification and extraction should occur in one strict-output request. A separate classification call is justified only when:

- the document is image-only and page triage reduces OCR cost;
- it contains multiple logical sections requiring different extraction schemas;
- the first result is `unknown/mixed` and user confirmation is needed before extraction.

Cross-document association should normally be deterministic and user-confirmed, not another model call.

### 7.3 Bounded OCR/vision for genuinely scanned documents

The exact SiCare 2315F3 sample proves that selectable-text-only support will not cover the supplied pilot set. Implement a bounded OCR/vision fallback as part of the approved architecture.

- Trigger only when text extraction yields no usable content.
- Limit to 10 pages for the pilot, with a clear page/size error above the limit.
- Render page thumbnails for one low-cost page-role request.
- Render only relevant identity/composition pages at higher resolution for strict extraction.
- Persist OCR text and page evidence so retries and edits require no new model call.
- Use `store=False` and the existing confidential-document processing terms.
- If the approved OCR/vision service is temporarily unavailable, retain the stored document in a retryable state and show a clear image-only processing error. Do not fabricate an empty formulation or silently fall back to unsupported text extraction.

### 7.4 Caching and safe diagnostics

Cache extraction by:

```text
organisation_id + file_sha256 + extraction_schema_version + model_configuration
```

Do not share confidential extraction data across organisations. Reuse the persisted extraction after navigation, restart, material-usage edits or attachment of the same saved supplier document to a later formulation. Reuse is allowed only when the exact file hash, extraction schema version and model configuration match. Otherwise reprocess the already stored private binary into a new extraction version; do not ask the user to upload it again. Record safe model name, response ID, attempt, token usage and failure category; never log document contents, prompts or keys.

---

## 8. Schema-specific extraction and validation

### 8.1 Finished-product formulation

Extract material rows rather than assuming every row is an INCI ingredient:

- submitted material/ingredient name;
- explicit trade name and supplier;
- product code;
- finished-product usage quantity;
- direct INCI/CAS where supplied;
- concentration semantics and basis;
- source evidence.

Classify each row as `direct_ingredient`, `trade_material`, or `unresolved_entry`. A row is not a trade material merely because its name is absent from the INCI catalogue.

### 8.2 Ingredient list

Extract identity facts and any explicit quantity. Missing concentration remains missing. This route can still prepare an identity-only canonical formulation for bounded screening, with concentration-dependent checks reported as incomplete.

### 8.3 Supplier composition and SDS composition sections

Extract:

- supplier, trade name, product/item code and document revision;
- constituent names and CAS identifiers;
- raw concentration text;
- structured composition semantics;
- legend and code relationships;
- units and bases;
- page/snippet/cell evidence;
- disclosure limitations explicitly stated by the document;
- role labels such as manufacturing additive;
- conflicting or repeated disclosures.

Safety exposure values, occupational limits, physicochemical percentages and hazard text must not become composition rows.

### 8.4 Deterministic legend resolver

Add `backend/app/services/composition_legends.py`.

1. Extract legend entries with evidence.
2. Validate that codes are unique within that legend.
3. Validate operators and numeric ordering.
4. Require every reported constituent code to reference a legend entry from the same document/revision.
5. Convert the entry to `CompositionQuantity` deterministically.
6. Preserve the reported code and raw legend wording.
7. If a code is missing or ambiguous, mark that constituent unresolved and request confirmation.

For OPTASENSE, `C` becomes the source-backed interval 25-50%, `D` becomes 10-25%, and `F` becomes 1-5%. Endpoint inclusivity remains unspecified unless the legend says otherwise.

### 8.5 Special composition semantics

- `qsp 100`: store `remainder_to_total(100%)`. Derive a remainder only when the disclosure is confirmed complete and the other compatible constituents are sufficiently quantified. Otherwise keep the constituent quantity unresolved/approximate.
- `max. 1`: upper bound 1%, with source wording retained.
- `~25` or approximately 25: approximate 25%, never exact.
- Independently reported ranges: preserve them even if extrema do not sum to exactly 100.
- Missing unit/basis: no inferred percent unless the table/legend explicitly establishes it.

### 8.6 Deterministic concentration validation safeguards

Validation occurs before calculation and is independent of AI confidence.

- Numeric values must be finite and non-negative. A percentage endpoint above 100% is invalid for a single constituent unless the source uses a different explicit unit/basis, which remains unconverted and unresolved.
- A range requires `lower <= upper`; its operators and endpoint inclusivity remain exactly as reported. An approximate value remains approximate through multiplication and aggregation.
- Units, concentration bases and preparation stages must be explicitly compatible. Regulens performs no implicit conversion between percent, ppm, mg/kg, supplier-material composition and finished-product concentration.
- A coded concentration is usable only when a unique legend entry from the same document revision resolves it. Missing, duplicated or ambiguous legends produce blocking structured issues.
- An unknown or missing quantity remains unknown; it is never treated as zero or silently excluded from completeness calculations.
- If exact percentages in a disclosure total above 100%, or the sum of all minimum/lower bounds exceeds 100%, create `impossible_composition_total` and withhold calculation. The sum of independent upper bounds exceeding 100% is not by itself an error.
- If a supplier asserts complete disclosure but exact values total materially below 100% with no valid remainder constituent, create an incomplete-disclosure issue. Preserve a documented tolerance only for rounding; record that tolerance and never use it to repair source data.
- `qsp 100` may be derived only when exactly one remainder constituent exists, the disclosure is confirmed complete, all other contributing quantities use compatible percent semantics, and the calculated remainder is non-negative. For interval inputs, derive `[100 - sum(upper), 100 - sum(lower)]`; invalid or negative bounds block calculation instead of being clamped.
- Approximate values and intervals crossing a regulatory threshold cannot be presented as a precise pass. They retain their existing conservative deterministic range/approximation outcome.
- Conflicting supplier statements are not averaged. Until a governing revision is confirmed, the affected material remains unresolved.
- Aggregation requires a verified identical regulatory identity and compatible quantity semantics. Unverified names, ambiguous identities and related-but-distinct chemical forms remain separate and generate `unverified_identity_aggregation` when a merge would otherwise occur.

Validation produces structured issues with source evidence and reviewer actions. It does not mutate the extracted source value to make a composition appear internally consistent.

---

## 9. Deterministic calculation and aggregation

Create `backend/app/services/material_calculation.py` as pure, extensively tested functions.

### 9.1 Contribution calculation

For compatible non-negative percentage quantities:

```text
constituent_finished_product_percent
  = material_finished_product_usage_percent
  * constituent_composition_percent
  / 100
```

Examples:

- 2% OPTASENSE with code C (25-50%) yields a 0.5-1.0% contribution.
- 4% SiCare material with a 25-35% constituent yields a 1.0-1.4% contribution.

Interval multiplication uses the lower endpoints for the lower result and upper endpoints for the upper result because all supported concentrations are non-negative. Preserve open/closed/unspecified boundary information conservatively.

Approximate input produces an approximate calculated result. Unknown usage or unknown composition produces an unresolved contribution, not zero.

### 9.2 Aggregation

Aggregate only when identity resolution establishes the same verified identity group and quantity units/bases/stages are compatible.

```text
aggregate = sum(direct additions) + sum(material contributions)
```

For intervals, use interval addition. Preserve each contribution for audit and evidence.

Do not aggregate:

- unresolved identities;
- merely similar names;
- distinct salts/forms without an approved group relationship;
- incompatible units/bases/stages;
- a trade-name parent with its constituents.

Such cases remain separate and require review.

### 9.3 Recalculation lifecycle

Recalculate when any of these change:

- material usage;
- constituent quantity;
- document association;
- selected governing supplier document;
- constituent identity resolution;
- direct ingredient quantity;
- user confirmation affecting disclosure completeness.

Recalculation is deterministic and must not invoke AI. Store a snapshot containing assembly revision, algorithm version, inputs, contributions, aggregate rows and unresolved issues.

Before writing that snapshot, calculation must verify the active governing-document set and contribution-lineage uniqueness. The snapshot records every included, withheld and unresolved constituent so a missing row cannot disappear silently between assembly and screening.

---

## 10. Regulatory screening integration

Add an assembly adapter in `backend/app/services/formulation.py` or a focused `assembly.py` module:

```text
confirmed assembly
  -> deterministic calculation snapshot
  -> aggregated/direct ingredient rows
  -> existing FormulationRequest
  -> existing screen_formulation()
```

Behavior by available information:

| Scenario | Screening behavior |
|---|---|
| Complete formulation, calculated exact/ranged contributions | Run all applicable Parts I-V checks supported by current inputs. |
| Ingredient list without concentrations | Run identity/prohibition and other non-concentration-dependent checks; report concentration-dependent checks as incomplete. |
| Supplier documents without finished-product usage | Show disclosed identities and potentially applicable records; do not treat supplier composition as final-product concentration. |
| Missing or unresolved supplier disclosure | Preserve incomplete disposition and name the missing material/constituent fact. |
| Ambiguous association or identity | Do not include an uncertain candidate as a confirmed calculated ingredient; expose the unresolved item. |

Screening snapshots should store:

- the flat canonical request used by the engine;
- assembly revision;
- calculation snapshot and contribution provenance;
- document IDs/revisions used;
- regulatory dataset identity;
- immutable result snapshot.

Historical runs remain unchanged. Editing material usage and screening again creates a new immutable run.

### 10.1 Screening completeness contract

`AssemblyResult` is part of the screening input contract, not only a frontend warning. Persist the following with every new screening run:

- `assembly_completeness` (`complete`, `partial`, or `blocked`);
- all assembly issues and their source targets;
- the set of documents/materials/constituents included in the canonical request;
- unresolved or excluded records and the exact reason each was withheld;
- the scope of checks that could and could not be performed;
- the calculation snapshot and provenance used by each submitted ingredient.

Disposition rules are conservative:

1. `fully_evaluated` is permitted only when the assembly is complete, every relevant raw material is associated, every required constituent identity and concentration is resolved, disclosure needed for the claimed scope is complete, and every applicable regulatory condition was evaluated.
2. `partially_evaluated` is used when safe checks were performed but any relevant raw material, disclosed constituent, concentration, identity, association or supplier disclosure remains unresolved.
3. A blocked or unresolved identity with no safe checks remains not evaluated for that item; it must still appear in the result as an unresolved screening input.
4. A confirmed prohibited/exceeded finding remains visible even when another input is unresolved, but the overall disposition remains partial.
5. No unresolved item may be omitted merely because it was excluded from the flat `FormulationRequest`. The result snapshot must name it and explain why evaluation was withheld.
6. Neither deterministic nor AI-generated text may describe the complete product as compliant, approved or fully evaluated when the assembly or rule evaluation is incomplete.

Preparation may proceed to bounded partial screening when useful checks are safe, but the API and UI must display the structured coverage limitation. Blocking calculation errors such as impossible totals or conflicting governing documents must prevent use of affected calculated concentrations; they do not erase unrelated safe checks.

---

## 11. Frontend workflow

Reuse the existing case and Agent workspace. Add progressive disclosure instead of separate applications.

### 11.1 Components

Recommended component-level changes:

- `frontend/src/pages/CasePage.tsx`
  - multi-file input;
  - `Upload new` and `Add saved supplier document` actions;
  - create a version with a batch;
  - show upload and per-document processing summary.
- `frontend/src/pages/AgentPage.tsx`
  - retain the current ingredient table for direct ingredients;
  - add document and material sections before canonical preview.
- New `frontend/src/components/DocumentProcessingList.tsx`
  - filename, detected role, status, page count, retry and role correction.
- New `frontend/src/components/SupplierDocumentPicker.tsx`
  - organisation-private search by supplier, trade name, product code, revision and filename;
  - processing/readiness, last-used and revision indicators;
  - attach the exact selected revision without re-uploading.
- New `DocumentAssociationPanel.tsx`
  - suggested relationships with evidence and explicit confirmation.
- New `MaterialAssemblyTable.tsx`
  - direct ingredients and trade materials at the primary level.
- New `MaterialConstituentPanel.tsx`
  - expandable constituent breakdown, composition, identity, source and corrections.
- New `CalculatedFormulationPreview.tsx`
  - aggregate finished-product concentrations with expandable contribution formula/source.

### 11.2 User journey

1. **Upload or reuse:** upload one or several files, or attach a previously processed supplier/SDS document from the organisation library; no preselected document mode.
2. **Document understanding:** show detected roles and uncertainty per document.
3. **Relationship confirmation:** show formulation-to-material and material-to-supplier-document suggestions.
4. **Material review:** edit usage, constituent identities, ranges, codes and legends.
5. **Calculated preview:** show direct and calculated/aggregated finished-product ingredients.
6. **Confirm and screen:** use the existing primary action and existing deterministic engine.
7. **Findings:** reuse current results, evidence drawer, reviewer notes and follow-ups.

The main material table should not expand every supplier constituent by default. Use an explicit constituent drawer/details panel to keep the workspace readable.

### 11.3 Required warnings

Use precise, non-alarmist limitations:

- `Finished-product usage is missing for MATRIXYL 3000 MBAL. Its disclosed constituents can be reviewed, but their final-product concentrations cannot be calculated.`
- `This SDS may contain only reportable ingredients. Screening covers the disclosed composition and does not establish complete product coverage.`
- `Code C was interpreted using the legend on page 1 of this document: 25-50%.`
- `Two documents may describe the same material but contain different composition ranges. Confirm which revision applies.`

### 11.4 Preserve the ordinary INCI workflow

Multi-document processing extends the existing case/formulation workspace; it is not a parallel application or a mandatory advanced mode.

- A single ordinary CSV/XLSX/selectable-text PDF containing direct INCI rows follows the current short path: upload, review/edit the same ingredient table, prepare and screen.
- The documents/materials/association UI stays collapsed or absent when no trade material or multi-document ambiguity is detected.
- The saved-document picker appears as a secondary action and does not add a required step to ordinary direct-INCI uploads.
- The existing canonical `FormulationRequest`, row editor, clarification reconciliation, results table, evidence drawer, reviewer notes and follow-ups remain the shared workflow for both simple and assembled inputs.
- Existing one-file routes remain compatible during migration and delegate to the same document/assembly services; there must not be two implementations of regulatory preparation.
- Adding a supporting document later enriches the same formulation version and invalidates only derived assembly/calculation state. It does not discard confirmed direct-ingredient edits.
- Users are never required to classify a straightforward direct-INCI file manually merely because the advanced architecture exists.

Regression tests must compare the canonical request and findings for representative one-file cases before and after this extension, including CSV, XLSX and selectable-text PDF uploads.

---

## 12. Findings and explanation integration

The current findings drawer already separates deterministic evidence from human review. Extend its structured provenance rather than adding a separate explanation system.

Add optional calculation evidence:

- parent trade material and supplier;
- finished-product usage;
- constituent composition quantity/code;
- deterministic calculation expression;
- contribution range;
- aggregate total and other contributions;
- source document/page.

The main finding remains concise:

1. one title;
2. one summary;
3. one deduplicated checklist;
4. compact submitted/calculated versus regulatory limit;
5. expandable regulatory and calculation provenance.

The explanation model receives only the deterministic finding and structured calculation/source facts. It may simplify wording but cannot change quantities, identities, completeness or regulatory outcomes.

When a finding is based on a calculated contribution, its explanation must clearly distinguish supplier-material composition from finished-product concentration. It must state any approximate/range semantics and incomplete-assembly limitation, and it must not turn a range that crosses a legal threshold into a definite within-limit conclusion. Deterministic explanation tests assert the finding, limit, calculated quantity, provenance and reviewer action before any optional model wording is accepted.

---

## 13. Failure recovery, security and privacy

### 13.1 Per-document recovery

- Persist each file before parsing/model calls.
- Persist parse/classification/extraction states independently.
- Make each processing request idempotent by document hash, extraction schema, model configuration and persisted `processing_key`.
- Acquire a time-bounded processing lease with `processor_run_id`, heartbeat and optimistic revision; a stale worker cannot commit over a newer attempt.
- Retry only failed, interrupted or stale documents. Retry reuses the stored private file and increments attempt diagnostics instead of uploading again.
- Keep successful document results when another file fails.
- Allow role/association correction without rerunning extraction.
- Allow material usage edits and recalculation without AI.
- Detect stale revisions and return 409.
- On serverless timeout or process loss, retain the last durable stage and mark the expired lease retryable rather than leaving an indefinite `processing` state.
- After page refresh, hydrate every document and assembly status from the database. Do not automatically start a second run while a valid lease is active.
- Commit extraction output and its terminal status together. Never expose a partial payload as `ready`.
- Rebuilding assembly after a retry uses stable document/material/constituent IDs and lineage keys so it cannot double-count previously processed rows.
- Attaching an already-ready saved supplier document creates a formulation-local snapshot without acquiring a new processing lease or making a model call. If its extraction is stale, reprocessing operates on the stored private file and preserves the previous extraction for existing attachments.

The recovery state machine is:

```text
uploaded -> parsing -> classifying -> extracting -> needs_confirmation | ready
                       \-> interrupted | failed -> retry (new lease/attempt)
```

`interrupted` means the last request did not reach an atomic terminal commit; it is not evidence that extraction failed. A configurable lease timeout, rather than browser connection state, determines when takeover is safe.

### 13.2 Confidentiality

- Keep all documents in the existing private bucket.
- Issue only short-lived authorised download URLs.
- Never expose service-role credentials to the browser.
- Treat all document text as untrusted prompt content.
- Use strict schemas and source-reference validation.
- Keep `store=False` for model calls.
- Do not log prompts, full extracted contents or raw formulation data.
- Scope any extraction cache to the organisation.

### 13.3 Deletion

Deleting a formulation version removes its formulation-scoped file objects and document attachments before cascading assembly state, screening runs and review records. It must not delete organisation-library supplier files referenced by other or future formulations. Account/organisation deletion gathers both version-scoped and supplier-library paths. A supplier-library document may be archived at any time, but permanent deletion is blocked while an attachment references it so historical provenance cannot be broken.

---

## 14. Ordered implementation phases

### Phase 0 - Sample fixtures and capability verification

**Files/modules**

- `backend/tests/fixtures/trade_materials/`
- `backend/tests/test_document_intake.py`
- `docs/TRADE_NAME_COMPOSITION_IMPLEMENTATION_PLAN.md`

**Build**

- Create redacted/synthetic fixtures matching OPTASENSE code legends, VISCOPTIMA ranges, MATRIXYL special quantities and SiCare SDS layout.
- Record expected source-backed extraction outputs.
- Record the exact-parser SiCare verification: `parse_formulation_upload()` returns `agent_pdf_text_unavailable` for the supplied 454,224-byte file.
- Approve the confidential-document processing terms/provider for the bounded OCR/vision path and validate it only on PDFs that fail local text extraction.

**Verify**

- Every expected value is traced to the supplied sample page.
- No confidential sample content is committed unless explicitly approved; prefer synthetic fixtures.
- The supplied SiCare file fails the local text path for the recorded reason and succeeds only through the approved bounded OCR/vision adapter; a synthetic image-only equivalent covers CI regression.

### Phase 1 - Domain models and deterministic quantity/legend logic

**Files/modules**

- new `backend/app/models/document_intake.py`
- new `backend/app/services/composition_legends.py`
- new `backend/app/services/material_calculation.py`
- extend `frontend/src/types/agent.ts` or add `frontend/src/types/documentIntake.ts`

**Build**

- Document roles/evidence.
- Supplier materials/constituents.
- Composition quantity including coded range and remainder-to-total.
- Deterministic legend resolution, interval multiplication and aggregation.

**Tests**

- OPTASENSE A-H legend.
- unknown/missing code.
- explicit and open ranges.
- approximate, maximum and qsp semantics.
- duplicate verified constituents and incompatible identities.
- impossible exact totals, lower-bound totals above 100%, and valid overlapping upper ranges;
- incompatible units/bases/stages and unknown quantities never treated as zero;
- qsp with zero, one and multiple remainder constituents;
- unverified identities never aggregated;
- no AI arithmetic.

**Completion gate**

- Pure unit tests cover every quantity type and boundary behavior.

### Phase 2 - Persistence, storage and APIs

**Files/modules**

- new Supabase migration under `supabase/migrations/`
- `backend/app/models/cases.py`
- `backend/app/services/supabase_gateway.py`
- `backend/app/routes/cases.py`
- `backend/tests/test_persistent_cases.py`
- Supabase RLS tests under `supabase/tests/database/`

**Build**

- `supplier_documents` organisation-library table, `formulation_documents` attachments and RLS.
- assembly/calculation JSONB fields.
- multi-file create, add-document, saved-document search and attach endpoints.
- per-document status/retry and secure file deletion.
- idempotency keys, processing leases/heartbeats and stale-run recovery;
- explicit document revision/supersession and one governing source per material.

**Tests**

- cross-organisation isolation;
- partial batch failure;
- application restart/resume;
- multiple private files and deletion;
- revision conflicts;
- duplicate upload reuse without duplicate records or contributions;
- reuse of one processed SDS across two cases without a second upload or extraction call;
- cross-organisation saved-document search/attachment denial;
- formulation deletion detaches but retains the reusable supplier document;
- archive and referenced-document deletion safeguards;
- exact revision/extraction pinning for historical formulations;
- interrupted request, stale lease takeover and refresh-safe resume;
- retry after terminal failure without re-upload;
- immutable screenings remain unchanged.

**Completion gate**

- A formulation version with three documents can be closed/reopened with all processing and association state intact, and an organisation can attach one of its ready supplier documents to a later version without uploading or processing it again.

### Phase 3 - Parsing, classification and schema-specific extraction

**Files/modules**

- `backend/app/services/agent_csv.py` (generalise to document parsing result)
- new `backend/app/services/document_classifier.py`
- new `backend/app/services/document_extraction.py`
- focused extensions to `backend/app/services/formulation_agent.py`
- `backend/app/config.py`

**Build**

- deterministic structured-file fast path;
- document classification schema;
- supplier composition extraction schema;
- document-local legend validation;
- optional bounded OCR/vision adapter;
- cheap-model and fallback-model routing;
- per-document diagnostics and caching.
- organisation-library extraction reuse keyed by exact hash/schema/model configuration;
- reprocessing from the stored private binary when the extraction schema changes.

**Tests**

- all four sample structures;
- false finished-formulation classification guard;
- SDS safety data excluded;
- multiple logical sections;
- prompt-injection content;
- model retry/escalation budgets;
- no model call for deterministic fixtures.
- no parser/model call when a compatible ready saved supplier document is attached;
- schema-version mismatch creates a new extraction result from storage without changing existing formulation snapshots.

**Completion gate**

- Expected sample fields and pages are reproduced exactly and all unsupported facts remain unresolved.

### Phase 4 - Assembly, association and canonical preparation

**Files/modules**

- new `backend/app/services/formulation_assembly.py`
- extend `backend/app/services/formulation.py`
- extend Agent/case routes for assembly edits
- backend assembly tests

**Build**

- deterministic association suggestions;
- explicit confirmation state;
- direct ingredient/trade material separation;
- calculated contributions and aggregation;
- canonical `FormulationRequest` adapter;
- completeness/incomplete-disclosure issues.

**Tests**

- one formulation plus several supplier documents;
- documents without formulation;
- ambiguous association;
- same constituent in multiple blends;
- direct plus blend contribution;
- missing usage;
- conflicting supplier documents;
- duplicate files and duplicate filenames with different content;
- multiple ingredient lists without double-counting;
- multiple finished formulations require split/selection;
- governing revision changes invalidate/rebuild derived state;
- unresolved material, missing concentration, incomplete disclosure and ambiguous identity persist as structured assembly issues;
- recalculation after edits.

**Completion gate**

- Changing one material usage updates derived concentrations without an AI call and produces a traceable canonical request.

### Phase 5 - Frontend workflow

**Files/modules**

- `frontend/src/pages/CasePage.tsx`
- `frontend/src/pages/AgentPage.tsx`
- `frontend/src/api/cases.ts`
- new components listed in Section 11
- focused CSS and tests

**Build**

- multi-file upload;
- searchable saved supplier-document picker and exact revision selection;
- per-document progress/retry;
- role and association correction;
- material usage and constituent editing;
- calculated preview and provenance;
- responsive, accessible interaction.

**Tests**

- keyboard/focus behavior;
- upload partial failure;
- role correction;
- material expansion;
- legend confirmation;
- calculation refresh;
- saved reload;
- existing one-file workflow regression.
- ordinary direct-INCI CSV/XLSX/PDF keeps the current compact workflow and canonical findings;
- page refresh during processing hydrates persisted state and does not start a duplicate run;
- duplicate/conflicting/revised documents are presented without accidental merging.
- attaching a saved SDS shows its ready extraction and provenance without a file chooser or new processing spinner;
- archived documents are absent from new selection but remain readable from formulations that already use them.

**Completion gate**

- A reviewer can upload a formulation, attach previously processed supplier PDFs from the private library, confirm associations, enter usage and reach the existing screening results without another application mode.

### Phase 6 - Screening and findings integration

**Files/modules**

- `backend/app/routes/cases.py`
- `backend/app/services/evidence.py`
- `backend/app/services/screening_report.py`
- `frontend/src/components/EvidenceDrawer.tsx`
- screening/report regression tests

**Build**

- calculation snapshot attached to screening request/result evidence;
- incomplete assembly disposition;
- contribution provenance in drawer/PDF report;
- no change to regulatory rule selection or limits.

**Tests**

- ranges below/crossing/above limits;
- prohibited constituent with unknown usage;
- unresolved identity;
- incomplete SDS;
- aggregate exceedance;
- calculated ranges entirely below, crossing and entirely above a regulatory limit;
- calculated approximate values and missing units/bases;
- adverse finding plus unresolved assembly retains the adverse result and partial disposition;
- unresolved/excluded materials remain visible in persisted screening outcomes;
- deterministic explanation states supplier composition, material usage and final-product contribution correctly;
- optional AI wording cannot change the deterministic finding, limit, disposition or reviewer action;
- historical snapshot compatibility.

**Completion gate**

- The engine receives only confirmed direct/calculated ingredients, persists all withheld/unresolved inputs beside them, and never displays full evaluation when assembly inputs or applicable regulatory conditions are incomplete.

---

## 15. Tuesday pilot MVP

### Must be included

1. Multi-file upload into one formulation version.
2. Per-document status and recoverable retry.
3. Automatic proposed roles with visible evidence and manual correction.
4. Supplier trade-material parent with constituent children.
5. OPTASENSE document-local code legend extraction and deterministic resolution.
6. Explicit ranges, approximate, upper-bound and qsp/max preservation.
7. Optional finished-product usage per trade material.
8. Deterministic range contribution calculation.
9. Aggregation of the same verified identity across materials/direct additions.
10. Missing-usage and incomplete-disclosure warnings.
11. Existing Parts I-V screening of the confirmed calculated formulation.
12. Page/document/material calculation provenance.
13. Persistence and reload.
14. Existing single-file formulation regression.
15. Structured assembly completeness and persisted unresolved/excluded inputs in every screening run.
16. Duplicate, conflict and document-revision safeguards that prevent accidental merging/double-counting.
17. Idempotent processing, stale-state recovery and safe resume after refresh or server restart.
18. Bounded OCR/vision fallback for genuinely image-only PDFs, including the supplied SiCare sample.
19. Organisation-private saved supplier-document library with exact-revision reuse across cases and formulation versions.

### OCR/vision pilot boundary

- Bounded OCR/vision is part of the approved scope for PDFs that fail the actual local text parser; it is not used for selectable-text documents.
- The supplied SiCare file is a required image-only regression case because the current parser was directly verified to return `agent_pdf_text_unavailable`.
- If the configured OCR/vision provider is unavailable or has not passed privacy and extraction validation, the application must fail clearly and preserve the document for retry. It must not fabricate an empty extraction or mark the acceptance case as passed.

### Defer until after the pilot

- general OCR for long or poor-quality scans;
- handwriting;
- automatic fuzzy trade-name linking without confirmation;
- public, marketplace-wide or cross-organisation supplier-document sharing (private reuse within the same organisation is included);
- automatic supplier-document version precedence;
- asynchronous queue/worker infrastructure unless serverless limits force it;
- arbitrary chemical/unit conversions;
- automatic conclusions from incomplete proprietary disclosures;
- supplier collaboration/email requests;
- advanced formulation comparison;
- label checking.

---

## 16. Objective end-to-end acceptance criteria

1. A user creates a case and uploads a finished-product formulation plus OPTASENSE and MATRIXYL supplier PDFs together.
2. Regulens creates one formulation version with three private document records.
3. The documents are classified using their contents, with page/snippet evidence.
4. The user can correct every proposed role and association.
5. OPTASENSE code `C` resolves only through the page-1 legend to 25-50%; missing legend codes remain unresolved.
6. MATRIXYL approximate, `qsp 100` and `max. 1` values remain distinct and are not converted to false exact values.
7. VISCOPTIMA lower/upper bounds remain intact and are not treated as a finished-product formulation.
8. The exact supplied SiCare file first returns no usable local text, then the bounded OCR/vision path produces the six source-backed page-2 composition rows while hazard statements do not become ingredients.
9. Without material usage, disclosed constituents can be reviewed but final concentration remains unknown.
10. After usage is entered, Regulens calculates each constituent contribution deterministically and displays the formula/source.
11. Contributions for the same verified identity are aggregated; unresolved or distinct forms are not.
12. Editing usage recalculates without an AI call.
13. Confirming the assembly produces the existing canonical `FormulationRequest`.
14. The existing Parts I-V engine screens that request without treating trade-name parents as ingredients.
15. Missing disclosure, identity or association produces an incomplete/partial disposition, never unsupported clearance.
16. The user leaves, returns and sees the same documents, associations, edits, calculations and unresolved items.
17. Re-screening after an edit creates a new immutable run; the older run retains its original input, calculation and dataset version.
18. A second organisation cannot read any document, extraction, material, calculation or screening state.
19. Existing CSV/XLSX/single-PDF cases continue to work.
20. Test diagnostics report model calls and token usage, proving deterministic files and recalculation use zero paid model calls.
21. An unresolved trade material, incomplete supplier disclosure, missing constituent concentration or ambiguous identity remains a structured `AssemblyIssue`, survives reload and appears in every resulting screening snapshot.
22. A run containing any relevant unresolved assembly input or withheld regulatory condition cannot have `fully_evaluated` disposition or product-compliance wording.
23. A confirmed prohibited/exceeded constituent remains an adverse finding even when another material is unresolved; the overall coverage is still partial.
24. Uploading the same file twice to one formulation version reuses the existing document and never duplicates a material, constituent or calculated contribution.
25. Two files with the same name but different bytes remain distinct. Conflicting supplier statements are preserved and blocked from calculation until one governing revision is confirmed.
26. A batch containing two finished formulations cannot be merged; the user must select or split them into separate formulation versions.
27. Multiple ingredient lists can contribute only once per source lineage, and rows aggregate only after verified identity matching.
28. Exact percentages or minimum bounds that make a composition exceed 100% block the affected calculation. Overlapping upper ranges alone do not trigger a false error.
29. Incompatible units, bases or preparation stages are neither converted nor aggregated. Missing values are never treated as zero.
30. `qsp 100` is derived only with one remainder constituent and a complete compatible disclosure; invalid, negative or ambiguous remainders remain unresolved.
31. Approximate and ranged calculated contributions preserve their qualifiers and produce conservative below/crossing/above-limit regulatory outcomes.
32. A timed-out or interrupted interpretation can be resumed from the stored file. Stale leases are recoverable, active leases are not duplicated and a refreshed browser shows persisted progress.
33. Selecting a newer supplier revision invalidates the derived calculation, preserves the earlier source and immutable screening run, and recalculates without AI.
34. A simple direct-INCI CSV, XLSX or selectable-text PDF does not show unnecessary material-association steps and produces the same canonical request/findings as the existing workflow.
35. Explanations for calculated findings state the supplier concentration, material usage, final-product contribution, regulatory limit and remaining uncertainty without allowing optional AI wording to change the deterministic result.
36. PDF/report evidence identifies every contributing document, page, material and formula, and names unresolved inputs rather than silently omitting them.
37. After an SDS/MSDS or supplier composition is processed and confirmed once, it appears in that organisation's saved-document picker with supplier, trade name, product code, revision and processing status where available.
38. The same organisation can attach that exact saved document to a later case/formulation without selecting a local file, uploading bytes again or repeating compatible parsing/AI extraction.
39. Attaching a saved supplier document creates a formulation-local extraction/association snapshot, so later library metadata edits, reprocessing or revisions do not silently change existing formulations or screening runs.
40. A changed supplier file creates a distinct revision. Existing formulations stay pinned to the old revision until the reviewer explicitly selects the new one.
41. A second organisation cannot discover, search, attach, download or infer the existence/hash of another organisation's saved supplier documents.
42. Deleting a formulation detaches the library document but retains it for future reuse; archiving hides it from new selections, and permanent deletion cannot break an existing reference.
43. Uploading an already-saved exact file transparently reuses the private library record while still preventing duplicate contributions inside the new formulation.
44. A confirmed saved SDS/MSDS remains available after refresh, sign-out/sign-in and backend restart, and can be reused in a later formulation check without the original local file.

---

## 17. Recommended implementation order for the pilot

The smallest reliable path is:

1. quantity/legend/calculation domain and tests;
2. organisation-private supplier-document persistence, formulation attachments and multi-file/reuse API;
3. deterministic parsing plus low-cost supplier extraction;
4. assembly and association confirmation;
5. compact frontend material workflow and saved supplier-document picker;
6. canonical adapter and existing screening integration;
7. bounded OCR/vision for locally verified image-only documents, with page limits and source evidence;
8. full regression, security and production-build verification.

Do not begin with a general-purpose multi-agent document system or a new regulatory engine. The core product improvement is a trustworthy, source-backed assembly layer between uploaded documents and the already working canonical screening input.

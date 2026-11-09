import { AlertCircle, ArrowRight, CheckCircle2, Clipboard, ExternalLink, FileStack, FileUp, LoaderCircle, MoreHorizontal, Paperclip, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { attachSupplierDocument, deleteCase, deleteFormulationVersion, getCase, getSupplierDocumentFile, interpretFormulationDocument, listSupplierDocuments, retrySupplierDocument, updateSupplierDocument, uploadCaseFormulation, uploadCaseSupplierDocuments, uploadFormulationDocuments } from "../api/cases";
import { CaseDeleteDialog } from "../components/CaseDeleteDialog";
import { TypedDeleteDialog } from "../components/TypedDeleteDialog";
import { addReviewerNote, getCaseActivity, getReviewOverview } from "../api/review";
import { currentVersion, formatRelativeDate, resolveCaseAction, reviewerItemsRemaining, workflowFilter, workflowLabel } from "../lib/cases";
import { reviewStatusPresentation } from "../lib/reviewPresentation";
import type { CaseView, DocumentRole, FormulationVersionSummary, SupplierDocument } from "../types/cases";
import type { ActivityContext, CaseActivity, CaseActivityEntry, ReviewerNote, ReviewOverview } from "../types/review";

type LoadState = "loading" | "available" | "unavailable";

function activitySummary(entry: CaseActivityEntry): string {
  if (entry.kind === "note") return entry.body;
  if (entry.kind === "follow_up") return `${entry.status === "open" ? "Open follow-up" : "Resolved follow-up"}: ${entry.action_text}`;
  return `Reviewer status updated to ${reviewStatusPresentation[entry.review_status].label}`;
}

function activityTarget(caseId: string, entry: CaseActivityEntry): string | null {
  const context = entry.context;
  if (!context.formulation_version_id) return null;
  const base = `/cases/${caseId}/formulations/${context.formulation_version_id}`;
  if (context.target_type === "finding" && context.screening_run_id && context.submitted_row_number) {
    return `${base}?tab=results&run=${encodeURIComponent(context.screening_run_id)}&row=${context.submitted_row_number}&drawer=review`;
  }
  if (context.target_type === "clarification" && context.clarification_id) {
    return `${base}?tab=formulation&clarification=${encodeURIComponent(context.clarification_id)}`;
  }
  return `${base}?tab=formulation`;
}

function caseNoteActivity(note: ReviewerNote, caseName: string): CaseActivityEntry {
  const context: ActivityContext = {
    case_id: note.case_id,
    case_name: caseName,
    target_type: "case",
    target_label: "Case",
    formulation_version_id: null,
    formulation_version_number: null,
    screening_run_id: null,
    screening_run_number: null,
    screening_at: null,
    regulatory_dataset_id: null,
    clarification_id: null,
    clarification_question_key: null,
    clarification_question: null,
    source_row_number: null,
    review_item_id: null,
    submitted_row_number: null,
    ingredient_name: null,
    engine_finding: null,
  };
  return { id: note.id, kind: "note", occurred_at: note.created_at, author_name: note.author_name, context, body: note.body };
}

export function CasePage() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const productInput = useRef<HTMLInputElement>(null);
  const supplierInput = useRef<HTMLInputElement>(null);
  const [record, setRecord] = useState<CaseView | null>(null);
  const [recordLoading, setRecordLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [productUploading, setProductUploading] = useState(false);
  const [supplierUploading, setSupplierUploading] = useState(false);
  const [supplierDocuments, setSupplierDocuments] = useState<SupplierDocument[]>([]);
  const [supplierDocumentsLoading, setSupplierDocumentsLoading] = useState(true);
  const [selectedSavedDocument, setSelectedSavedDocument] = useState("");
  const [supplierActionId, setSupplierActionId] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [versionToDelete, setVersionToDelete] = useState<FormulationVersionSummary | null>(null);
  const [versionDeleting, setVersionDeleting] = useState(false);
  const [versionDeleteError, setVersionDeleteError] = useState<string | null>(null);
  const [overview, setOverview] = useState<ReviewOverview | null>(null);
  const [overviewState, setOverviewState] = useState<LoadState>("loading");
  const [activity, setActivity] = useState<CaseActivity | null>(null);
  const [activityState, setActivityState] = useState<LoadState>("loading");
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [noteSaved, setNoteSaved] = useState(false);
  const [copied, setCopied] = useState(false);

  const loadOverview = useCallback(async (background = false) => {
    if (!background) setOverviewState("loading");
    try {
      setOverview(await getReviewOverview(caseId));
      setOverviewState("available");
    } catch {
      if (!background) {
        setOverview(null);
        setOverviewState("unavailable");
      }
    }
  }, [caseId]);

  const loadActivity = useCallback(async (background = false) => {
    if (!background) setActivityState("loading");
    try {
      setActivity(await getCaseActivity(caseId));
      setActivityState("available");
    } catch {
      if (!background) {
        setActivity(null);
        setActivityState("unavailable");
      }
    }
  }, [caseId]);

  useEffect(() => {
    let active = true;
    setRecordLoading(true);
    void getCase(caseId)
      .then((value) => { if (active) setRecord(value); })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "The case could not be loaded."); })
      .finally(() => { if (active) setRecordLoading(false); });
    void loadOverview();
    void loadActivity();
    void listSupplierDocuments()
      .then((documents) => { if (active) setSupplierDocuments(documents); })
      .catch(() => undefined)
      .finally(() => { if (active) setSupplierDocumentsLoading(false); });
    return () => { active = false; };
  }, [caseId, loadActivity, loadOverview]);

  const uploadProductFormulation = async (selected?: FileList | null) => {
    const file = selected?.[0];
    if (!file || productUploading) return;
    setProductUploading(true);
    setError(null);
    setUploadNotice(null);
    try {
      const version = await uploadCaseFormulation(caseId, file);
      navigate(`/cases/${caseId}/formulations/${version.id}?tab=formulation`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The formulation could not be uploaded. Choose the file again to retry.");
    } finally {
      setProductUploading(false);
      if (productInput.current) productInput.current.value = "";
    }
  };

  const uploadSupplierSources = async (selected?: FileList | null) => {
    const files = Array.from(selected ?? []);
    if (!files.length || supplierUploading) return;
    setSupplierUploading(true);
    setError(null);
    setUploadNotice(null);
    try {
      const current = record ? currentVersion(record) : null;
      if (current) {
        const batch = await uploadFormulationDocuments(current.id, files);
        const queue = [...batch.documents];
        const processingFailures: string[] = [];
        const processNext = async (): Promise<void> => {
          const document = queue.shift();
          if (!document) return;
          try {
            await interpretFormulationDocument(document.id);
          } catch (caught) {
            processingFailures.push(`${document.original_filename}: ${caught instanceof Error ? caught.message : "processing failed"}`);
          }
          await processNext();
        };
        await Promise.all([processNext(), processNext()]);
        const failures = [...batch.failures.map((failure) => `${failure.filename}: ${failure.message}`), ...processingFailures];
        if (failures.length) setError(failures.join(" "));
        setUploadNotice(`${batch.documents.length} supplier document${batch.documents.length === 1 ? "" : "s"} attached to the current formulation.`);
      } else {
        const batch = await uploadCaseSupplierDocuments(caseId, files);
        setSupplierDocuments((current) => [
          ...batch.documents,
          ...current.filter((item) => !batch.documents.some((uploaded) => uploaded.id === item.id)),
        ]);
        const failures = batch.failures.map((failure) => `${failure.filename}: ${failure.message}`);
        if (failures.length) setError(failures.join(" "));
        setUploadNotice(`${batch.documents.length} supplier document${batch.documents.length === 1 ? "" : "s"} saved for standalone review. Add a product formulation before finished-product screening.`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The supplier documents could not be uploaded.");
    } finally {
      setSupplierUploading(false);
      if (supplierInput.current) supplierInput.current.value = "";
    }
  };

  const reuseSupplierDocument = async () => {
    const current = record ? currentVersion(record) : null;
    if (!current || !selectedSavedDocument || supplierUploading) return;
    setSupplierUploading(true); setError(null); setUploadNotice(null);
    try {
      await attachSupplierDocument(current.id, selectedSavedDocument);
      const document = supplierDocuments.find((item) => item.id === selectedSavedDocument);
      setSelectedSavedDocument("");
      setUploadNotice(`${document?.trade_name || document?.original_filename || "Saved supplier document"} attached to the current formulation.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The saved supplier document could not be attached.");
    } finally {
      setSupplierUploading(false);
    }
  };

  const openSupplierDocument = async (document: SupplierDocument) => {
    try {
      const source = await getSupplierDocumentFile(document.id);
      window.open(source.url, "_blank", "noopener,noreferrer");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The private supplier source could not be opened.");
    }
  };

  const confirmStandaloneSupplierRole = async (document: SupplierDocument, role: DocumentRole) => {
    setSupplierActionId(document.id); setError(null);
    try {
      const updated = await updateSupplierDocument(document.id, document.revision, {
        confirmed_roles: [role],
        library_status: "available",
      });
      setSupplierDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
      setUploadNotice(`${updated.trade_name || updated.original_filename} is ready for reuse.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The supplier document role could not be confirmed.");
    } finally {
      setSupplierActionId(null);
    }
  };

  const retryStandaloneSupplier = async (document: SupplierDocument) => {
    setSupplierActionId(document.id); setError(null);
    try {
      const updated = await retrySupplierDocument(document.id);
      setSupplierDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
      setUploadNotice(`${updated.trade_name || updated.original_filename} was reprocessed.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The supplier document could not be reprocessed.");
    } finally {
      setSupplierActionId(null);
    }
  };

  const submitNote = async (event: FormEvent) => {
    event.preventDefault();
    if (!note.trim()) return;
    setNoteSaving(true);
    setNoteError(null);
    setNoteSaved(false);
    try {
      const saved = await addReviewerNote(caseId, "case", null, note.trim());
      setActivity((current) => ({
        case_id: caseId,
        entries: [caseNoteActivity(saved, record?.name ?? "Case"), ...(current?.entries ?? []).filter((entry) => !(entry.kind === "note" && entry.id === saved.id))],
      }));
      setActivityState("available");
      setOverview((current) => current ? {
        ...current,
        note_count: current.note_count + 1,
        last_review_activity_at: saved.created_at,
        recent_case_notes: [saved, ...current.recent_case_notes.filter((item) => item.id !== saved.id)].slice(0, 5),
      } : current);
      setNote("");
      setNoteOpen(false);
      setNoteSaved(true);
    } catch (caught) {
      setNoteError(caught instanceof Error ? caught.message : "Case note could not be saved. Your draft has been kept.");
    } finally {
      setNoteSaving(false);
    }
  };

  const copyOutstanding = async () => {
    if (!record || !overview?.open_follow_up_items.length) return;
    const text = [`${record.name} — outstanding information and actions`, "", ...overview.open_follow_up_items.map((item, index) => `${index + 1}. ${item.target_label ?? "Case"}: ${item.action_text}${item.details ? ` — ${item.details}` : ""}`)].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("The outstanding requests could not be copied. Please copy them manually.");
    }
  };

  const remove = async () => {
    if (!record || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteCase(record.id);
      navigate("/cases", { replace: true, state: { deletedCaseName: record.name } });
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : "The case could not be deleted. No case records were removed.");
    } finally { setDeleting(false); }
  };

  const removeVersion = async () => {
    if (!versionToDelete || versionDeleting) return;
    setVersionDeleting(true); setVersionDeleteError(null);
    try {
      await deleteFormulationVersion(versionToDelete.id);
      setRecord((current) => current ? { ...current, formulations: current.formulations.filter((item) => item.id !== versionToDelete.id) } : current);
      setVersionToDelete(null);
      setOverview(null); setActivity(null);
      void loadOverview(); void loadActivity();
    } catch (caught) {
      setVersionDeleteError(caught instanceof Error ? caught.message : "The formulation version could not be deleted.");
    } finally { setVersionDeleting(false); }
  };

  if (recordLoading) return <main className="workspace"><div className="case-page"><div className="case-overview-skeleton" aria-label="Loading case"><span /><span /><span /></div></div></main>;
  if (!record) return <main className="workspace"><div className="case-page"><div className="page-error-row" role="alert"><AlertCircle size={16} />{error || "The case could not be loaded."}</div></div></main>;

  const latestVersion = currentVersion(record);
  const remainingReviews = reviewerItemsRemaining(overview);
  const action = resolveCaseAction(record, overview);
  const screenedVersionId = overview?.latest_screening_formulation_version_id ?? latestVersion?.id ?? null;
  const activeRunQuery = overview?.latest_screening_run_id ? `&run=${encodeURIComponent(overview.latest_screening_run_id)}` : "";
  const resultsTarget = screenedVersionId ? `/cases/${caseId}/formulations/${screenedVersionId}?tab=results${activeRunQuery}` : null;
  const formulationTarget = latestVersion ? `/cases/${caseId}/formulations/${latestVersion.id}?tab=formulation` : null;
  const activityVersionId = screenedVersionId ?? latestVersion?.id;
  const activityTargetUrl = activityVersionId ? `/cases/${caseId}/formulations/${activityVersionId}?tab=activity${activeRunQuery}` : null;
  const continueTarget = action.href;
  const hasAttention = Boolean(overview && (overview.attention_findings || overview.unresolved_clarifications || remainingReviews || overview.open_follow_ups));

  return (
    <main className="workspace">
      <div className="case-page case-overview-page" aria-hidden={deleteDialogOpen || Boolean(versionToDelete)}>
        <header className="case-header case-overview-header">
          <div>
            <Link className="breadcrumb-link" to="/cases">← Cases</Link>
            <div className="case-title-line"><h1 className="page-title">{record.name}</h1>{record.status === "archived" && <span className="quiet-badge">Archived</span>}</div>
            <p className="case-identity-meta">{record.client_name || "No client recorded"}<span aria-hidden="true">·</span>Singapore{latestVersion && <><span aria-hidden="true">·</span>Current version {latestVersion.version_number}</>}</p>
          </div>
          <div className="case-header-actions">
            {continueTarget ? <Link className="primary-button" to={continueTarget}>{action.label}<ArrowRight size={15} /></Link> : null}
            <details className="case-more-menu"><summary className="icon-button" aria-label="More case actions"><MoreHorizontal size={18} /></summary><div><button className="danger-menu-button" type="button" onClick={() => { setDeleteDialogOpen(true); setDeleteError(null); }} disabled={deleting}><Trash2 size={14} /> Delete case</button></div></details>
          </div>
        </header>

        {error && <div className="page-error-row" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        {uploadNotice && <div className="case-upload-success" role="status"><CheckCircle2 size={17} /><span>{uploadNotice}</span></div>}

        <section className="case-current-formulation" aria-labelledby="current-formulation-heading">
          <div>
            <p className="eyebrow">Current formulation</p>
            <h2 id="current-formulation-heading">{latestVersion?.original_filename || "No product formulation uploaded"}</h2>
            <p>{latestVersion ? `Version ${latestVersion.version_number} · ${workflowLabel({ ...record, latest_formulation: latestVersion })} · ${latestVersion.screening_count} screening run${latestVersion.screening_count === 1 ? "" : "s"}` : "Upload one finished formulation or ingredient list to start interpretation and screening."}</p>
          </div>
          {latestVersion ? <Link className="secondary-button" to={`/cases/${caseId}/formulations/${latestVersion.id}?tab=${latestVersion.status === "screened" ? "results" : "formulation"}`}>Open current formulation <ArrowRight size={14} /></Link> : <a className="primary-button" href="#case-upload-formulation">Upload Formulation <ArrowRight size={14} /></a>}
        </section>

        <section className="case-upload-hub" aria-labelledby="upload-hub-heading">
          <div className="section-heading-row compact"><div><h2 id="upload-hub-heading" className="section-title">Add documents</h2><p>Choose the section first so Regulens knows how each file should be interpreted.</p></div></div>
          <div className="case-upload-grid">
            <article id="case-upload-formulation" className="case-upload-card">
              <FileUp size={21} aria-hidden="true" />
              <div><h3>Product Formulation</h3><p>Upload one Excel, CSV or selectable-text PDF containing the finished formulation or ingredient list. All workbook sheets are read.</p></div>
              <button className="primary-button" type="button" onClick={() => productInput.current?.click()} disabled={productUploading || supplierUploading} aria-busy={productUploading}>{productUploading ? <><LoaderCircle className="button-spinner" size={15} aria-hidden="true" /> Uploading and interpreting…</> : latestVersion ? "Upload new formulation version" : "Upload formulation"}</button>
              <input ref={productInput} className="sr-only" type="file" accept=".csv,.xlsx,.xls,.pdf" aria-label="Choose product formulation" onChange={(event) => void uploadProductFormulation(event.target.files)} />
            </article>
            <article className="case-upload-card">
              <FileStack size={21} aria-hidden="true" />
              <div><h3>Supplier Documents <span>Optional</span></h3><p>Upload multiple SDS/MSDS or supplier composition PDFs. Without a product formulation, Regulens saves them for standalone trade-name review and clearly limits screening.</p></div>
              <button className="secondary-button" type="button" onClick={() => supplierInput.current?.click()} disabled={supplierUploading || productUploading} aria-busy={supplierUploading}>{supplierUploading ? <><LoaderCircle className="button-spinner" size={15} aria-hidden="true" /> Processing supplier files…</> : "Upload supplier documents"}</button>
              <input ref={supplierInput} className="sr-only" type="file" multiple accept=".pdf,.csv,.tsv,.txt,.xlsx,.xls,.json" aria-label="Choose supplier documents" onChange={(event) => void uploadSupplierSources(event.target.files)} />
              {latestVersion ? <div className="case-saved-supplier-picker"><label htmlFor="saved-supplier-document-case">Reuse saved supplier document</label><div><select id="saved-supplier-document-case" value={selectedSavedDocument} disabled={supplierUploading || supplierDocumentsLoading} onChange={(event) => setSelectedSavedDocument(event.target.value)}><option value="">{supplierDocumentsLoading ? "Loading saved documents…" : "Choose saved SDS or composition"}</option>{supplierDocuments.filter((item) => item.library_status === "available").map((item) => <option key={item.id} value={item.id}>{[item.trade_name, item.product_code, item.supplier_name, item.original_filename].filter((value, index, all) => Boolean(value) && all.indexOf(value) === index).join(" · ")}</option>)}</select><button className="secondary-button" type="button" disabled={!selectedSavedDocument || supplierUploading} onClick={() => void reuseSupplierDocument()}><Paperclip size={14} /> Attach</button></div></div> : null}
            </article>
          </div>
          {!latestVersion && supplierDocuments.length > 0 ? (
            <div className="standalone-supplier-review">
              <div><strong>Supplier-only review</strong><span>These workspace documents are retained and interpreted, but no finished-product screening or concentration aggregation is possible until a product formulation is uploaded.</span></div>
              <ul>{supplierDocuments.slice(0, 6).map((document) => {
                const isActing = supplierActionId === document.id;
                const canRetry = document.processing_status === "interrupted" || document.processing_status === "failed";
                const needsRole = document.library_status === "needs_confirmation" && document.processing_status === "ready";
                return (
                  <li key={document.id}>
                    <span><strong>{document.trade_name || document.product_code || document.original_filename}</strong><small>{document.supplier_name || document.original_filename} · {document.processing_status.replaceAll("_", " ")}</small></span>
                    <div className="standalone-supplier-actions">
                      {canRetry ? <button className="secondary-button compact" type="button" disabled={isActing} aria-busy={isActing} onClick={() => void retryStandaloneSupplier(document)}>{isActing ? <><LoaderCircle className="button-spinner" size={13} aria-hidden="true" /> Reprocessing…</> : "Retry processing"}</button> : null}
                      {needsRole ? <><button className="secondary-button compact" type="button" disabled={isActing} onClick={() => void confirmStandaloneSupplierRole(document, "supplier_composition")}>Supplier composition</button><button className="secondary-button compact" type="button" disabled={isActing} onClick={() => void confirmStandaloneSupplierRole(document, "sds_msds")}>SDS / MSDS</button></> : null}
                      <button className="text-button" type="button" onClick={() => void openSupplierDocument(document)}>View source <ExternalLink size={13} /></button>
                    </div>
                  </li>
                );
              })}</ul>
            </div>
          ) : null}
        </section>

        <section className="case-progress-summary" aria-label="Case progress">
          {overviewState === "loading" ? <span>Loading review progress…</span> : overviewState === "unavailable" || !overview ? <span>Review information is temporarily unavailable. Formulation versions remain accessible.</span> : (
            <>
              <span><strong>{overview.ingredients_screened}</strong> ingredients screened</span>
              <span className="is-attention"><strong>{overview.attention_findings}</strong> ingredient results need attention</span>
              <span><strong>{overview.unresolved_clarifications}</strong> input clarifications</span>
              <span><strong>{remainingReviews}</strong> reviewer actions remaining</span>
              <span><strong>{overview.open_follow_ups}</strong> open follow-ups</span>
            </>
          )}
        </section>

        <section className="case-attention-section" aria-labelledby="case-attention-heading">
          <div className="section-heading-row compact"><div><h2 id="case-attention-heading" className="section-title">What needs attention</h2><p>Outstanding input and professional review work for this case.</p></div>{overview?.open_follow_up_items.length ? <button className="secondary-button compact" type="button" onClick={() => void copyOutstanding()}><Clipboard size={14} /> {copied ? "Copied" : "Copy requests"}</button> : null}</div>
          {overviewState === "loading" ? <p className="muted-loading">Loading outstanding work…</p> : overviewState === "unavailable" || !overview ? <div className="inline-notice">Review information unavailable. Open a formulation version to continue working.</div> : hasAttention ? (
            <div className="attention-action-list">
              {overview.unresolved_clarifications > 0 && formulationTarget && <Link to={formulationTarget}><span><strong>Resolve input clarifications</strong><small>Confirm interpreted source values before screening.</small></span><ArrowRight size={15} /></Link>}
              {overview.attention_findings > 0 && resultsTarget && <Link to={resultsTarget}><span><strong>Inspect regulatory results needing attention</strong><small>Review the underlying findings and source evidence.</small></span><ArrowRight size={15} /></Link>}
              {(remainingReviews ?? 0) > 0 && resultsTarget && <Link to={`${resultsTarget}&resume=review&drawer=review`}><span><strong>Continue the reviewer workflow</strong><small>Record the remaining professional review decisions.</small></span><ArrowRight size={15} /></Link>}
              {overview.open_follow_ups > 0 && activityTargetUrl && <Link to={`${activityTargetUrl}&activity=open-followups`}><span><strong>Review open follow-ups</strong><small>Resolve outstanding information and actions.</small></span><ArrowRight size={15} /></Link>}
            </div>
          ) : overview.latest_screening_run_id ? <div className="quiet-completion"><strong>No open professional review tasks</strong><p>This does not indicate product approval or full regulatory compliance. The screening remains bounded by the saved dataset and submitted facts.</p></div> : <div className="quiet-completion"><strong>No saved screening yet</strong><p>Continue the current formulation when its input is ready.</p></div>}
        </section>

        <section className="case-section" aria-labelledby="versions-heading">
          <div className="section-heading-row compact"><div><h2 id="versions-heading" className="section-title">Formulation versions</h2><p>Current and historical input records remain independently navigable.</p></div></div>
          {record.formulations.length === 0 ? (
            <div className="empty-case compact"><h3>No formulation versions yet</h3><p>New versions appear here after using Product Formulation above. This section is only for viewing formulation and screening history.</p></div>
          ) : (
            <div className="version-list polished-version-list">
              {record.formulations.map((version, index) => (
                <div className="version-list-row" key={version.id}>
                  <Link to={`/cases/${caseId}/formulations/${version.id}?tab=${version.status === "screened" ? "results" : "formulation"}`}>
                    <div><strong>Version {version.version_number}</strong>{index === 0 && <span className="quiet-badge">Current</span>}<small>{version.original_filename || "Filename unavailable"}</small></div>
                    <div><span className={`workflow-state-badge is-${workflowFilter({ ...record, latest_formulation: version })}`}>{workflowLabel({ ...record, latest_formulation: version })}</span><small>{formatRelativeDate(version.updated_at)} · {version.screening_count} screening run{version.screening_count === 1 ? "" : "s"}</small></div>
                    <span className="version-row-action">{version.status === "failed" ? "Retry interpretation" : "Open"}<ArrowRight size={14} /></span>
                  </Link>
                  <button className="version-delete-button" type="button" aria-label={`Delete formulation version ${version.version_number}`} onClick={() => { setVersionToDelete(version); setVersionDeleteError(null); }}><Trash2 size={15} /></button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="case-section case-activity-preview" aria-labelledby="activity-preview-heading">
          <div className="section-heading-row compact"><div><h2 id="activity-preview-heading" className="section-title">Recent notes &amp; activity</h2><p>Latest professional observations and actions across this case.</p></div><div className="section-actions"><button className="secondary-button compact" type="button" onClick={() => { setNoteOpen((value) => !value); setNoteSaved(false); }}>Add case note</button>{activityTargetUrl && <Link className="text-button" to={activityTargetUrl}>View all <ArrowRight size={14} /></Link>}</div></div>
          {noteOpen && <form className="case-note-composer" onSubmit={submitNote}><label htmlFor="case-note-body">Case note</label><textarea id="case-note-body" autoFocus value={note} maxLength={4000} placeholder="Record an observation or professional decision about this case" onChange={(event) => { setNote(event.target.value); setNoteError(null); }} />{noteError && <p className="field-error" role="alert">{noteError}</p>}<div><button className="primary-button" disabled={noteSaving || !note.trim()} aria-busy={noteSaving}>{noteSaving ? <><LoaderCircle className="button-spinner" size={14} aria-hidden="true" /> Saving…</> : noteError ? "Retry save" : "Save note"}</button><button className="text-button" type="button" onClick={() => setNoteOpen(false)} disabled={noteSaving}>Cancel</button></div></form>}
          {noteSaved && <p className="local-save-state" role="status">Case note saved.</p>}
          {activityState === "loading" ? <p className="muted-loading">Loading recent activity…</p> : activityState === "unavailable" ? <div className="inline-notice">Recent activity is temporarily unavailable.</div> : !activity?.entries.length ? <div className="activity-empty"><strong>No professional activity yet</strong><p>Add a case note here, or create finding notes and follow-ups while reviewing results.</p></div> : <ol className="activity-preview-list">{activity.entries.slice(0, 3).map((entry) => { const target = activityTarget(caseId, entry); return <li key={`${entry.kind}-${entry.id}`}><div><span className={`activity-kind is-${entry.kind}`}>{entry.kind === "review_update" ? "Review update" : entry.kind === "follow_up" ? "Follow-up" : "Note"}</span><span>{entry.context.target_label}</span></div><p>{activitySummary(entry)}</p><small>{entry.author_name} · {formatRelativeDate(entry.occurred_at)}</small>{target && <Link to={target} aria-label={`Open ${entry.context.target_label}`}><ArrowRight size={14} /></Link>}</li>; })}</ol>}
        </section>
      </div>
      <CaseDeleteDialog caseName={deleteDialogOpen ? record.name : null} busy={deleting} error={deleteError} onCancel={() => { if (!deleting) { setDeleteDialogOpen(false); setDeleteError(null); } }} onConfirm={() => void remove()} />
      <TypedDeleteDialog open={Boolean(versionToDelete)} title={`Delete formulation version ${versionToDelete?.version_number ?? ""}?`} description="This permanently removes its uploaded file, interpretation, clarifications, screening runs, finding reviews, formulation and finding notes, and linked follow-ups. Case-level notes remain." actionLabel="Delete formulation" busy={versionDeleting} error={versionDeleteError} onCancel={() => { if (!versionDeleting) { setVersionToDelete(null); setVersionDeleteError(null); } }} onConfirm={() => void removeVersion()} />
    </main>
  );
}

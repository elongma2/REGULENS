import { AlertCircle, ArrowRight, Filter, MoreHorizontal, Plus, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { createCase, deleteCase, listCases } from "../api/cases";
import { CaseDeleteDialog } from "../components/CaseDeleteDialog";
import { currentVersion, formatRelativeDate, hasUnfinishedWork, resolveCaseAction, workflowFilter, workflowLabel, type CaseWorkflowFilter } from "../lib/cases";
import type { CaseView } from "../types/cases";

type LifecycleFilter = "active" | "archived" | "all";
type ReviewFilter = "all" | "needs_review" | "open_follow_ups" | "no_open_tasks" | "unavailable";

export function CasesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const creating = location.pathname.endsWith("/new");
  const [cases, setCases] = useState<CaseView[]>([]);
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [lifecycle, setLifecycle] = useState<LifecycleFilter>("active");
  const [workflow, setWorkflow] = useState<CaseWorkflowFilter>("all");
  const [review, setReview] = useState<ReviewFilter>("all");
  const [deleteTarget, setDeleteTarget] = useState<CaseView | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(() => (location.state as { deletedCaseName?: string } | null)?.deletedCaseName ? `“${(location.state as { deletedCaseName: string }).deletedCaseName}” was deleted.` : null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCases(await listCases());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Cases could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!(location.state as { deletedCaseName?: string } | null)?.deletedCaseName) return;
    navigate(location.pathname, { replace: true, state: null });
  }, [location.pathname, location.state, navigate]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const created = await createCase(name, client.trim() || null);
      navigate(`/cases/${created.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Case creation failed.");
    }
  };

  const filteredCases = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return cases.filter((record) => {
      const version = currentVersion(record);
      const summary = record.review_summary;
      const searchMatches = !needle || [record.name, record.client_name, version?.original_filename]
        .some((value) => value?.toLocaleLowerCase().includes(needle));
      const lifecycleMatches = lifecycle === "all" || record.status === lifecycle;
      const workflowMatches = workflow === "all" || workflowFilter(record) === workflow;
      const reviewMatches = review === "all"
        || (review === "unavailable" && summary == null)
        || (review === "needs_review" && Boolean(summary && summary.reviewer_items_remaining > 0))
        || (review === "open_follow_ups" && Boolean(summary && summary.open_follow_ups > 0))
        || (review === "no_open_tasks" && Boolean(summary?.latest_screening_run_id && summary.reviewer_items_remaining === 0 && summary.open_follow_ups === 0));
      return searchMatches && lifecycleMatches && workflowMatches && reviewMatches;
    });
  }, [cases, lifecycle, query, review, workflow]);

  const resumeCase = [...cases]
    .filter(hasUnfinishedWork)
    .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())[0] ?? null;
  const clearFilters = () => { setQuery(""); setLifecycle("active"); setWorkflow("all"); setReview("all"); };
  const secondaryFilterCount = Number(workflow !== "all") + Number(review !== "all");

  const removeCase = async () => {
    if (!deleteTarget || deletingId) return;
    setDeletingId(deleteTarget.id);
    setDeleteError(null);
    try {
      await deleteCase(deleteTarget.id);
      const deletedName = deleteTarget.name;
      setCases((current) => current.filter((record) => record.id !== deleteTarget.id));
      setDeleteTarget(null);
      setSuccessMessage(`“${deletedName}” was deleted.`);
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : "The case could not be deleted. No case records were removed.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <main className="workspace">
      <div className="case-page cases-index-page" aria-hidden={Boolean(deleteTarget)}>
        <header className="case-header compact-page-header">
          <div>
            <h1 className="page-title">Cases</h1>
            <p className="page-description">Find a product record, resume its review, or start a new case.</p>
          </div>
          <button className="primary-button" onClick={() => navigate("/cases/new")}><Plus size={15} /> New Case</button>
        </header>

        {error && <div className="page-error-row" role="alert"><AlertCircle size={16} /><span>{error}</span><button className="text-button" type="button" onClick={() => void load()}>Retry</button></div>}
        {successMessage && <div className="success-notice" role="status"><span>{successMessage}</span><button className="icon-button" type="button" aria-label="Dismiss message" onClick={() => setSuccessMessage(null)}><X size={14} /></button></div>}

        {creating && (
          <form className="case-form compact-case-form" onSubmit={submit}>
            <div><h2 className="section-title">Create a case</h2><p>A case keeps formulation versions, screening history, notes, and reviewer work together.</p></div>
            <label>Case / product name<input autoFocus required value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>Client name <span>Optional</span><input value={client} onChange={(event) => setClient(event.target.value)} /></label>
            <div className="form-actions"><button className="primary-button">Create case</button><button type="button" className="secondary-button" onClick={() => navigate("/cases")}>Cancel</button></div>
          </form>
        )}

        {!creating && !loading && resumeCase && (
          <Link to={resolveCaseAction(resumeCase, resumeCase.review_summary).href ?? `/cases/${resumeCase.id}`} className="resume-case-row">
            <div><span>Continue where you left off</span><strong>{resumeCase.name}</strong></div>
            <div><span>{resolveCaseAction(resumeCase, resumeCase.review_summary).label}</span><small>Updated {formatRelativeDate(resumeCase.updated_at)}</small></div>
            <ArrowRight size={17} aria-hidden="true" />
          </Link>
        )}

        <section className="case-directory" aria-labelledby="case-directory-heading">
          <div className="case-directory-toolbar">
            <div><h2 id="case-directory-heading" className="section-title">Case directory</h2><span>{loading ? "Loading cases" : `${filteredCases.length} of ${cases.length} cases`}</span></div>
            <label className="case-search"><span className="sr-only">Search cases</span><Search size={15} aria-hidden="true" /><input type="search" value={query} placeholder="Search case, client, or file" onChange={(event) => setQuery(event.target.value)} /></label>
            <label><span>Lifecycle</span><select value={lifecycle} onChange={(event) => setLifecycle(event.target.value as LifecycleFilter)}><option value="active">Active</option><option value="archived">Archived</option><option value="all">All</option></select></label>
            <details className="case-filter-disclosure">
              <summary><Filter size={14} /> Filters{secondaryFilterCount > 0 && <span>{secondaryFilterCount}</span>}</summary>
              <div>
                <label><span>Workflow</span><select value={workflow} onChange={(event) => setWorkflow(event.target.value as CaseWorkflowFilter)}><option value="all">All stages</option><option value="awaiting_formulation">Awaiting formulation</option><option value="input">Input / clarification</option><option value="ready">Ready to screen</option><option value="screened">Screened</option><option value="failed">Failed</option></select></label>
                <label><span>Review</span><select value={review} onChange={(event) => setReview(event.target.value as ReviewFilter)}><option value="all">All review states</option><option value="needs_review">Needs reviewer action</option><option value="open_follow_ups">Open follow-ups</option><option value="no_open_tasks">No open reviewer tasks</option><option value="unavailable">Information unavailable</option></select></label>
                {secondaryFilterCount > 0 && <button className="text-button" type="button" onClick={() => { setWorkflow("all"); setReview("all"); }}>Clear filters</button>}
              </div>
            </details>
          </div>

          {loading ? (
            <div className="case-list case-list-loading" aria-label="Loading cases">{[0, 1, 2].map((item) => <div className="case-row-skeleton" key={item}><span /><span /><span /></div>)}</div>
          ) : cases.length === 0 ? (
            <section className="empty-case"><h2>No cases yet</h2><p>Create a case to keep formulation versions, screening history, and professional review work together.</p><button className="primary-button" onClick={() => navigate("/cases/new")}><Plus size={15} /> Create Case</button></section>
          ) : filteredCases.length === 0 ? (
            <section className="empty-case compact"><h3>No cases match these filters</h3><p>Change the search or clear the current filters.</p><button className="secondary-button" type="button" onClick={clearFilters}>Clear filters</button></section>
          ) : (
            <div className="case-list" role="list">
              {filteredCases.map((record) => {
                const version = currentVersion(record);
                const summary = record.review_summary;
                const action = resolveCaseAction(record, summary);
                return (
                  <div key={record.id} className="case-list-row" role="listitem">
                    <Link className="case-row-overview-link" to={`/cases/${record.id}`} aria-label={`Open ${record.name} overview`}>
                      <div className="case-row-identity"><strong>{record.name}</strong><span>{record.client_name || "No client recorded"}</span>{record.status === "archived" && <small className="quiet-badge">Archived</small>}</div>
                      <div className="case-row-workflow"><span className={`workflow-state-badge is-${workflowFilter(record)}`}>{workflowLabel(record)}</span><small>{version ? `Version ${version.version_number}${version.original_filename ? ` · ${version.original_filename}` : ""}` : "No formulation uploaded"}</small></div>
                      <div className="case-row-review">
                        {summary == null ? <span>Review information unavailable</span> : !summary.latest_screening_run_id ? <span>Not screened yet</span> : summary.reviewer_items_remaining > 0 ? <span><strong>{summary.reviewer_items_remaining}</strong> reviewer action{summary.reviewer_items_remaining === 1 ? "" : "s"} remaining</span> : <span>No open reviewer tasks</span>}
                        {summary && summary.open_follow_ups > 0 && <small>{summary.open_follow_ups} open follow-up{summary.open_follow_ups === 1 ? "" : "s"}</small>}
                      </div>
                    </Link>
                    {action.href ? <Link className="case-row-action" to={action.href}><strong>{action.label}</strong><small>Updated {formatRelativeDate(record.updated_at)}</small><ArrowRight size={15} aria-hidden="true" /></Link> : <Link className="case-row-action" to={`/cases/${record.id}`}><strong>{action.label}</strong><small>Updated {formatRelativeDate(record.updated_at)}</small><ArrowRight size={15} aria-hidden="true" /></Link>}
                    <details className="case-row-menu"><summary className="icon-button" aria-label={`More actions for ${record.name}`}><MoreHorizontal size={17} /></summary><div><button className="danger-menu-button" type="button" disabled={Boolean(deletingId)} onClick={() => { setDeleteTarget(record); setDeleteError(null); }}><Trash2 size={14} /> Delete case</button></div></details>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
      <CaseDeleteDialog caseName={deleteTarget?.name ?? null} busy={deletingId === deleteTarget?.id} error={deleteError} onCancel={() => { if (!deletingId) { setDeleteTarget(null); setDeleteError(null); } }} onConfirm={() => void removeCase()} />
    </main>
  );
}

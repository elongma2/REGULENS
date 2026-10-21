import { CheckCircle2, Filter, MessageSquarePlus, RotateCcw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { addReviewerNote, getCaseActivity, updateFollowUp } from "../api/review";
import { formatRelativeDate } from "../lib/cases";
import { reviewStatusPresentation } from "../lib/reviewPresentation";
import type { ActivityContext, ActivityContextType, CaseActivityEntry, FollowUpActivityEntry, ReviewerNote } from "../types/review";

type ActivityTypeFilter = "all" | "note" | "follow_up" | "review_update";
type ActivityState = "loading" | "available" | "unavailable";
const ACTIVITY_BATCH_SIZE = 50;

const typeLabels: Record<ActivityTypeFilter, string> = {
  all: "All activity",
  note: "Notes",
  follow_up: "Follow-ups",
  review_update: "Latest review updates",
};

function entryText(entry: CaseActivityEntry): string {
  if (entry.kind === "note") return entry.body;
  if (entry.kind === "follow_up") return `${entry.action_text} ${entry.details ?? ""}`;
  return `Reviewer status set to ${reviewStatusPresentation[entry.review_status].label}`;
}

function jumpTarget(caseId: string, entry: CaseActivityEntry): string | null {
  const context = entry.context;
  if (!context.formulation_version_id) return null;
  const base = `/cases/${caseId}/formulations/${context.formulation_version_id}`;
  if (context.target_type === "finding" && context.screening_run_id && context.submitted_row_number) {
    return `${base}?tab=results&run=${encodeURIComponent(context.screening_run_id)}&row=${context.submitted_row_number}&drawer=review`;
  }
  if (context.target_type === "clarification" && context.clarification_id) {
    return `${base}?tab=formulation&clarification=${encodeURIComponent(context.clarification_id)}`;
  }
  if (context.target_type === "formulation") return `${base}?tab=formulation`;
  return `${base}?tab=activity`;
}

function ContextDetails({ entry }: { entry: CaseActivityEntry }) {
  const { context } = entry;
  const hasDetails = Boolean(context.formulation_version_number || context.screening_run_number || context.screening_at || context.regulatory_dataset_id || context.submitted_row_number || context.engine_finding);
  if (!hasDetails) return null;
  return <details className="activity-context-details"><summary>Context details</summary><div>
    {context.formulation_version_number && <span>Formulation version <strong>{context.formulation_version_number}</strong></span>}
    {context.screening_run_number && <span>Screening run <strong>{context.screening_run_number}</strong></span>}
    {context.submitted_row_number && <span>Submitted row <strong>{context.submitted_row_number}</strong></span>}
    {context.screening_at && <span>Screened <strong>{new Date(context.screening_at).toLocaleString()}</strong></span>}
    {context.regulatory_dataset_id && <span>Dataset <strong>{context.regulatory_dataset_id}</strong></span>}
    {context.engine_finding && <span>Regulatory result <strong>{context.engine_finding.replaceAll("_", " ")}</strong></span>}
  </div></details>;
}

function caseNoteEntry(note: ReviewerNote, caseName: string): CaseActivityEntry {
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

export function NotesActivityPanel({
  caseId,
  initialOpenOnly = false,
  refreshToken = 0,
  onReviewDataChange,
}: {
  caseId: string;
  initialOpenOnly?: boolean;
  refreshToken?: number;
  onReviewDataChange?: () => void;
}) {
  const navigate = useNavigate();
  const loaded = useRef(false);
  const previousRefreshToken = useRef(refreshToken);
  const [entries, setEntries] = useState<CaseActivityEntry[]>([]);
  const [state, setState] = useState<ActivityState>("loading");
  const [query, setQuery] = useState("");
  const [type, setType] = useState<ActivityTypeFilter>(initialOpenOnly ? "follow_up" : "all");
  const [context, setContext] = useState<"all" | ActivityContextType>("all");
  const [openOnly, setOpenOnly] = useState(initialOpenOnly);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [updatingFollowUp, setUpdatingFollowUp] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState(false);
  const [visibleCount, setVisibleCount] = useState(ACTIVITY_BATCH_SIZE);
  const [followUpErrors, setFollowUpErrors] = useState<Record<string, string>>({});

  const load = useCallback(async (background = false) => {
    if (!background) setState("loading");
    setRefreshError(false);
    try {
      const activity = await getCaseActivity(caseId);
      setEntries(activity.entries);
      setState("available");
      loaded.current = true;
    } catch {
      if (background && loaded.current) setRefreshError(true);
      else setState("unavailable");
    }
  }, [caseId]);

  useEffect(() => {
    loaded.current = false;
    void load();
  }, [load]);
  useEffect(() => {
    if (previousRefreshToken.current === refreshToken) return;
    previousRefreshToken.current = refreshToken;
    if (loaded.current) void load(true);
  }, [load, refreshToken]);
  useEffect(() => {
    if (!initialOpenOnly) return;
    setType("follow_up");
    setOpenOnly(true);
  }, [initialOpenOnly]);

  const filteredEntries = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return entries.filter((entry) => {
      if (type !== "all" && entry.kind !== type) return false;
      if (context !== "all" && entry.context.target_type !== context) return false;
      if (openOnly && (entry.kind !== "follow_up" || entry.status !== "open")) return false;
      if (!needle) return true;
      return [
        entryText(entry), entry.author_name, entry.context.case_name, entry.context.target_label,
        entry.context.ingredient_name, entry.context.clarification_question, entry.context.engine_finding,
        entry.context.regulatory_dataset_id,
        entry.context.formulation_version_number ? `version ${entry.context.formulation_version_number}` : null,
        entry.context.screening_run_number ? `screening ${entry.context.screening_run_number}` : null,
        entry.context.submitted_row_number ? `row ${entry.context.submitted_row_number}` : null,
      ]
        .some((value) => value?.toLocaleLowerCase().includes(needle));
    });
  }, [context, entries, openOnly, query, type]);
  useEffect(() => { setVisibleCount(ACTIVITY_BATCH_SIZE); }, [context, openOnly, query, type]);
  const visibleEntries = filteredEntries.slice(0, visibleCount);

  const openFollowUps = entries.filter((entry): entry is FollowUpActivityEntry => entry.kind === "follow_up" && entry.status === "open");

  const submitNote = async (event: FormEvent) => {
    event.preventDefault();
    if (!noteDraft.trim()) return;
    setSavingNote(true);
    setSaveError(null);
    setSavedMessage(null);
    try {
      const saved = await addReviewerNote(caseId, "case", null, noteDraft.trim());
      const caseName = entries[0]?.context.case_name ?? "Case";
      setEntries((current) => [caseNoteEntry(saved, caseName), ...current.filter((entry) => !(entry.kind === "note" && entry.id === saved.id))]);
      setState("available");
      setNoteDraft("");
      setNoteOpen(false);
      setSavedMessage("Case note saved.");
      onReviewDataChange?.();
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : "The case note could not be saved. Your draft has been kept.");
    } finally {
      setSavingNote(false);
    }
  };

  const toggleFollowUp = async (entry: FollowUpActivityEntry) => {
    setUpdatingFollowUp(entry.id);
    setSaveError(null);
    setFollowUpErrors((current) => { const next = { ...current }; delete next[entry.id]; return next; });
    setSavedMessage(null);
    try {
      const saved = await updateFollowUp(entry.id, { status: entry.status === "open" ? "resolved" : "open" });
      setEntries((current) => current.map((item) => item.kind === "follow_up" && item.id === saved.id
        ? {
            ...item,
            action_text: saved.action_text,
            details: saved.details,
            status: saved.status,
            occurred_at: saved.updated_at,
            updated_at: saved.updated_at,
            resolved_at: saved.resolved_at,
          }
        : item));
      setSavedMessage(entry.status === "open" ? "Follow-up resolved." : "Follow-up reopened.");
      onReviewDataChange?.();
    } catch (caught) {
      setFollowUpErrors((current) => ({ ...current, [entry.id]: caught instanceof Error ? caught.message : "The follow-up could not be updated. Please retry." }));
    } finally {
      setUpdatingFollowUp(null);
    }
  };

  const clearFilters = () => { setQuery(""); setType("all"); setContext("all"); setOpenOnly(false); };

  return <div className="notes-activity-workspace">
    <header className="notes-activity-header">
      <div><h2 className="section-title">Notes &amp; Activity</h2><p>Case-wide professional notes, follow-ups, and latest reviewer-status updates with their original context.</p></div>
      <button className="secondary-button compact" type="button" onClick={() => { setNoteOpen((value) => !value); setSavedMessage(null); }}><MessageSquarePlus size={14} /> Add case note</button>
    </header>

    {noteOpen && <form className="case-note-composer activity-note-composer" onSubmit={submitNote}><label htmlFor="activity-case-note">Case note</label><textarea id="activity-case-note" autoFocus value={noteDraft} maxLength={4000} placeholder="Record an observation or professional decision about this case" onChange={(event) => { setNoteDraft(event.target.value); setSaveError(null); }} />{saveError && <p className="field-error" role="alert">{saveError}</p>}<div><button className="primary-button" disabled={savingNote || !noteDraft.trim()}>{savingNote ? "Saving…" : saveError ? "Retry save" : "Save note"}</button><button className="text-button" type="button" onClick={() => setNoteOpen(false)} disabled={savingNote}>Cancel</button></div></form>}
    {savedMessage && <p className="local-save-state" role="status">{savedMessage}</p>}
    {refreshError && <div className="inline-notice activity-local-message" role="status"><span>Showing saved activity. The latest refresh did not complete.</span><button className="text-button" type="button" onClick={() => void load(true)}>Retry</button></div>}

    <div className="activity-filter-bar" id="activity-filter-controls" tabIndex={-1}>
      <label className="activity-search"><span className="sr-only">Search notes and activity</span><Search size={15} /><input type="search" value={query} placeholder="Search notes, actions, context, or author" onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="activity-type-presets" aria-label="Activity type">{(Object.keys(typeLabels) as ActivityTypeFilter[]).map((value) => <button key={value} type="button" className={type === value ? "is-active" : ""} aria-pressed={type === value} onClick={() => setType(value)}>{typeLabels[value]}</button>)}</div>
      <details className="activity-filter-disclosure"><summary><Filter size={13} /> More filters{(context !== "all" || openOnly) && <span>{Number(context !== "all") + Number(openOnly)}</span>}</summary><div><label><span>Context</span><select value={context} onChange={(event) => setContext(event.target.value as "all" | ActivityContextType)}><option value="all">All contexts</option><option value="case">Case</option><option value="formulation">Formulation</option><option value="clarification">Clarification</option><option value="finding">Finding</option></select></label><label className="activity-open-toggle"><input type="checkbox" checked={openOnly} onChange={(event) => { setOpenOnly(event.target.checked); if (event.target.checked) setType("follow_up"); }} /> Open follow-ups only</label></div></details>
      <span>{state === "available" ? `${filteredEntries.length} of ${entries.length} entries` : ""}</span>
    </div>

    {state === "loading" ? <div className="activity-feed-loading" aria-label="Loading notes and activity">{[0, 1, 2].map((value) => <span key={value} />)}</div> : state === "unavailable" ? <div className="activity-state-panel"><strong>Notes and activity are temporarily unavailable</strong><p>The formulation and screening workspace remain usable.</p><button className="secondary-button" type="button" onClick={() => void load()}><RotateCcw size={14} /> Retry</button></div> : <>
      {openFollowUps.length > 0 && !openOnly && <section className="open-follow-up-section" aria-labelledby="open-followups-heading"><div><h3 id="open-followups-heading">Outstanding follow-ups</h3><button type="button" className="text-button" onClick={() => { setType("follow_up"); setOpenOnly(true); }}>Show all {openFollowUps.length}</button></div><ul>{openFollowUps.slice(0, 3).map((entry) => <li key={entry.id}><span><strong>{entry.action_text}</strong><small>{entry.context.target_label} · {entry.author_name}</small>{followUpErrors[entry.id] && <small className="activity-row-error" role="alert">{followUpErrors[entry.id]}</small>}</span><button type="button" className="text-button" disabled={updatingFollowUp === entry.id} onClick={() => void toggleFollowUp(entry)}>{updatingFollowUp === entry.id ? "Saving…" : followUpErrors[entry.id] ? "Retry resolve" : "Resolve"}</button></li>)}</ul></section>}

      {entries.length === 0 ? <div className="activity-state-panel"><strong>No professional activity yet</strong><p>Notes record observations or decisions. Follow-ups record required actions and keep their own Open or Resolved state.</p></div> : filteredEntries.length === 0 ? <div className="activity-state-panel"><strong>No activity matches these filters</strong><p>Change the search or clear the current filters.</p><button className="secondary-button" type="button" onClick={clearFilters}>Clear filters</button></div> : <><ol className="activity-feed">{visibleEntries.map((entry) => { const target = jumpTarget(caseId, entry); return <li key={`${entry.kind}-${entry.id}`} className={`activity-feed-item is-${entry.kind}`}>
        <div className="activity-feed-marker" aria-hidden="true">{entry.kind === "follow_up" ? <CheckCircle2 size={14} /> : entry.kind === "review_update" ? <RotateCcw size={13} /> : <MessageSquarePlus size={13} />}</div>
        <article>
          <header><div><span className={`activity-kind is-${entry.kind}`}>{entry.kind === "review_update" ? "Review update" : entry.kind === "follow_up" ? "Follow-up" : "Note"}</span>{entry.kind === "follow_up" && <span className={`follow-up-state is-${entry.status}`}>{entry.status}</span>}{target ? <button className="activity-context-link" type="button" onClick={() => navigate(target)}>{entry.context.target_label}</button> : <span className="activity-context-label">{entry.context.target_label}</span>}</div><time dateTime={entry.occurred_at}>{formatRelativeDate(entry.occurred_at)}</time></header>
          <p>{entryText(entry)}</p>
          <footer><span>{entry.author_name}{entry.kind === "follow_up" && entry.resolved_by_name ? ` · Resolved by ${entry.resolved_by_name}` : ""}</span>{entry.kind === "follow_up" && <button className="text-button" type="button" disabled={updatingFollowUp === entry.id} onClick={() => void toggleFollowUp(entry)}>{updatingFollowUp === entry.id ? "Saving…" : followUpErrors[entry.id] ? `Retry ${entry.status === "open" ? "resolve" : "reopen"}` : entry.status === "open" ? "Resolve" : "Reopen"}</button>}</footer>
          {entry.kind === "follow_up" && followUpErrors[entry.id] && <p className="activity-row-error" role="alert">{followUpErrors[entry.id]}</p>}
          <ContextDetails entry={entry} />
        </article>
      </li>; })}</ol>{visibleEntries.length < filteredEntries.length && <button className="activity-load-more" type="button" onClick={() => setVisibleCount((current) => current + ACTIVITY_BATCH_SIZE)}>Show older activity <span>{visibleEntries.length} of {filteredEntries.length}</span></button>}</>}
    </>}
    <p className="activity-history-note">Review updates show the latest persisted status for each finding, not a complete transition history.</p>
  </div>;
}

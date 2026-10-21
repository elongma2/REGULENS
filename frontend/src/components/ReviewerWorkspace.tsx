import { ClipboardCheck, MessageSquarePlus, Plus, RotateCcw } from "lucide-react";
import type { FormEvent } from "react";
import type { FollowUp, ReviewerNote, ReviewItem, ReviewStatus } from "../types/review";
import { idleWriteState, reviewStatusPresentation, type WriteState } from "../lib/reviewPresentation";

export function ReviewerWorkspace({
  reviewItem,
  notes,
  followUps,
  statusWriteState = idleWriteState,
  noteWriteState = idleWriteState,
  followUpWriteState = idleWriteState,
  pendingReviewStatus = null,
  followUpWriteStates = {},
  onStatusChange,
  onAddNote,
  onAddFollowUp,
  onToggleFollowUp,
  noteDraft,
  followUpDraft,
  onNoteDraftChange,
  onFollowUpDraftChange,
}: {
  reviewItem: ReviewItem | null;
  notes: ReviewerNote[];
  followUps: FollowUp[];
  statusWriteState?: WriteState;
  noteWriteState?: WriteState;
  followUpWriteState?: WriteState;
  pendingReviewStatus?: ReviewStatus | null;
  followUpWriteStates?: Record<string, WriteState>;
  onStatusChange: (status: ReviewStatus) => Promise<void>;
  onAddNote: (body: string) => Promise<void>;
  onAddFollowUp: (actionText: string) => Promise<void>;
  onToggleFollowUp: (followUp: FollowUp) => Promise<void>;
  noteDraft: string;
  followUpDraft: string;
  onNoteDraftChange: (value: string) => void;
  onFollowUpDraftChange: (value: string) => void;
}) {
  const submitNote = async (event: FormEvent) => {
    event.preventDefault();
    if (!noteDraft.trim()) return;
    try {
      await onAddNote(noteDraft.trim());
    } catch {
      // The parent presents the API error; retain the draft so the reviewer can retry.
    }
  };
  const submitAction = async (event: FormEvent) => {
    event.preventDefault();
    if (!followUpDraft.trim()) return;
    try {
      await onAddFollowUp(followUpDraft.trim());
    } catch {
      // The parent presents the API error; retain the draft so the reviewer can retry.
    }
  };
  const displayedReviewStatus = statusWriteState.phase === "saving" && pendingReviewStatus
    ? pendingReviewStatus
    : reviewItem?.review_status ?? "not_reviewed";

  return (
    <section className="reviewer-workspace" aria-labelledby="reviewer-workspace-heading">
      <div className="flex items-start gap-3">
        <ClipboardCheck className="mt-0.5 text-blue-700" size={18} />
        <div>
          <h3 id="reviewer-workspace-heading" className="drawer-title">Reviewer workspace</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">Your workflow status and notes do not change the regulatory finding.</p>
        </div>
      </div>

      {reviewItem?.requires_attention ? (
        <div className="field-label mt-4">
          <label htmlFor="reviewer-status">Review status</label>
          <select id="reviewer-status" className="field-control" value={displayedReviewStatus} disabled={statusWriteState.phase === "saving"} onChange={(event) => void onStatusChange(event.target.value as ReviewStatus)}>
            {Object.entries(reviewStatusPresentation).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}
          </select>
          {statusWriteState.phase !== "idle" && <span className={`write-state is-${statusWriteState.phase}`} role={statusWriteState.phase === "failed" ? "alert" : "status"}>{statusWriteState.phase === "saving" ? "Saving status…" : statusWriteState.phase === "saved" ? "Status saved" : statusWriteState.message ?? "Status could not be saved."}{statusWriteState.phase === "failed" && pendingReviewStatus && <button type="button" className="text-button" onClick={() => void onStatusChange(pendingReviewStatus)}>Retry</button>}</span>}
        </div>
      ) : <p className="mt-4 text-sm text-slate-600">This result does not require a reviewer status. You may still record a note.</p>}

      <div className="reviewer-workspace-section">
        <h4><MessageSquarePlus size={15} /> Reviewer notes</h4>
        {notes.length ? <ul className="review-note-list">{[...notes].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).map((item) => <li key={item.id}><p>{item.body}</p><small>{item.author_name} · {new Date(item.created_at).toLocaleString()}</small></li>)}</ul> : <p className="review-empty">No notes for this result.</p>}
        <form onSubmit={submitNote} className="review-inline-form">
          <textarea aria-label="Reviewer note" value={noteDraft} maxLength={4000} placeholder="Record an observation or decision" onChange={(event) => onNoteDraftChange(event.target.value)} />
          <button className="secondary-button" disabled={noteWriteState.phase === "saving" || !noteDraft.trim()}><Plus size={14} /> {noteWriteState.phase === "saving" ? "Saving…" : noteWriteState.phase === "failed" ? "Retry note" : "Add note"}</button>
        </form>
        {noteWriteState.phase !== "idle" && noteWriteState.phase !== "saving" && <p className={`write-state is-${noteWriteState.phase}`} role={noteWriteState.phase === "failed" ? "alert" : "status"}>{noteWriteState.phase === "saved" ? "Note saved" : noteWriteState.message ?? "The note could not be saved. Your draft was kept."}</p>}
      </div>

      <div className="reviewer-workspace-section">
        <h4><RotateCcw size={15} /> Follow-ups</h4>
        {followUps.length ? <ul className="follow-up-list">{[...followUps].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).map((item) => { const state = followUpWriteStates[item.id] ?? idleWriteState; return <li key={item.id}><div><strong>{item.action_text}</strong><small>{item.target_label ? `${item.target_label} · ` : ""}{item.status === "open" ? "Open" : "Resolved"} · {item.author_name} · {new Date(item.created_at).toLocaleString()}</small>{state.phase === "failed" && <span className="write-state is-failed" role="alert">{state.message}</span>}{state.phase === "saved" && <span className="write-state is-saved" role="status">Follow-up updated</span>}</div><button className="text-button" type="button" disabled={state.phase === "saving"} onClick={() => void onToggleFollowUp(item)}>{state.phase === "saving" ? "Saving…" : state.phase === "failed" ? `Retry ${item.status === "open" ? "resolve" : "reopen"}` : item.status === "open" ? "Resolve" : "Reopen"}</button></li>; })}</ul> : <p className="review-empty">No follow-ups for this result.</p>}
        <form onSubmit={submitAction} className="review-inline-form">
          <input aria-label="Follow-up action" value={followUpDraft} maxLength={1000} placeholder="Describe the information or action needed" onChange={(event) => onFollowUpDraftChange(event.target.value)} />
          <button className="secondary-button" disabled={followUpWriteState.phase === "saving" || !followUpDraft.trim()}><Plus size={14} /> {followUpWriteState.phase === "saving" ? "Saving…" : followUpWriteState.phase === "failed" ? "Retry follow-up" : "Add follow-up"}</button>
        </form>
        {followUpWriteState.phase !== "idle" && followUpWriteState.phase !== "saving" && <p className={`write-state is-${followUpWriteState.phase}`} role={followUpWriteState.phase === "failed" ? "alert" : "status"}>{followUpWriteState.phase === "saved" ? "Follow-up saved" : followUpWriteState.message ?? "The follow-up could not be saved. Your draft was kept."}</p>}
      </div>
    </section>
  );
}

import { ChevronLeft, ChevronRight, ExternalLink, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { FindingBadge } from "./FindingBadge";
import { IdentitySourceEvidence } from "./IdentitySourceEvidence";
import { ReviewerWorkspace } from "./ReviewerWorkspace";
import { SourceEvidence } from "./SourceEvidence";
import {
  basisLabel, comparatorLabel, comparisonRows, displayIngredientName, formatRuleConcentration,
  matchMethodLabel, preparationStageLabel, readableCode, reviewReasonLabel,
} from "../lib/presentation";
import { formatConcentration, isSingaporeEvaluation, regulationLabel } from "../lib/screening";
import { reviewStatusPresentation, type WriteState } from "../lib/reviewPresentation";
import type { InputProvenance } from "../types/agent";
import type { FollowUp, ReviewDataState, ReviewerNote, ReviewItem, ReviewStatus } from "../types/review";
import type { IngredientResult, RuleEvaluation, ScreeningResponse, SourceSnapshot } from "../types/screening";

export type DrawerTab = "evidence" | "review";

function concentrationComparison(evaluation: RuleEvaluation) {
  const submitted = evaluation.submitted_concentration;
  const limit = evaluation.evidence.concentration;
  if (evaluation.evaluation_status !== "deterministic" ||
    !["restriction_exceeded", "restriction_within_limit"].includes(evaluation.finding ?? "") ||
    !submitted || !limit || typeof limit.value !== "number" || submitted.unit !== limit.unit ||
    submitted.basis !== (limit.basis ?? null) || submitted.preparation_stage !== limit.preparation_stage ||
    limit.comparator !== "less_than_or_equal") return null;
  return { submitted, limit, difference: submitted.value - limit.value };
}

function ConcentrationComparison({ evaluation }: { evaluation: RuleEvaluation }) {
  const comparison = concentrationComparison(evaluation);
  if (!comparison) return null;
  return <div className="comparison-panel mt-3" aria-label="Concentration comparison">
    <div><span>Submitted concentration</span><strong>{formatConcentration(comparison.submitted)}</strong></div>
    <div><span>Singapore maximum</span><strong>{formatRuleConcentration(comparison.limit)}</strong></div>
    <div className="comparison-total"><span>Difference</span><strong className={comparison.difference > 0 ? "text-red-700" : "text-emerald-700"}>{comparison.difference > 0 ? "+" : ""}{comparison.difference.toFixed(2)} {comparison.limit.unit === "percent" ? "percentage points" : comparison.limit.unit}</strong></div>
  </div>;
}

export function EvidenceDrawer({
  result, sources, inputProvenance, explanationMetadata, reviewItem, reviewerNotes = [], followUps = [],
  reviewDataState = "not_applicable", hasPrevious = false, hasNext = false,
  statusWriteState, noteWriteState, followUpWriteState, pendingReviewStatus,
  followUpWriteStates,
  noteDraft = "", followUpDraft = "", onPrevious, onNext, onNoteDraftChange, onFollowUpDraftChange,
  activeTab: controlledActiveTab, onActiveTabChange,
  onReviewStatusChange, onAddReviewerNote, onAddFollowUp, onToggleFollowUp, onClose,
}: {
  result: IngredientResult | null;
  sources: SourceSnapshot[];
  inputProvenance?: InputProvenance | null;
  explanationMetadata?: ScreeningResponse["review_explanation_metadata"];
  reviewItem?: ReviewItem | null;
  reviewerNotes?: ReviewerNote[];
  followUps?: FollowUp[];
  statusWriteState?: WriteState;
  noteWriteState?: WriteState;
  followUpWriteState?: WriteState;
  pendingReviewStatus?: ReviewStatus | null;
  followUpWriteStates?: Record<string, WriteState>;
  reviewDataState?: ReviewDataState;
  hasPrevious?: boolean;
  hasNext?: boolean;
  noteDraft?: string;
  followUpDraft?: string;
  onPrevious?: () => void;
  onNext?: () => void;
  onNoteDraftChange?: (value: string) => void;
  onFollowUpDraftChange?: (value: string) => void;
  activeTab?: DrawerTab;
  onActiveTabChange?: (tab: DrawerTab) => void;
  onReviewStatusChange?: (status: ReviewStatus) => Promise<void>;
  onAddReviewerNote?: (body: string) => Promise<void>;
  onAddFollowUp?: (actionText: string) => Promise<void>;
  onToggleFollowUp?: (followUp: FollowUp) => Promise<void>;
  onClose: () => void;
}) {
  const [internalActiveTab, setInternalActiveTab] = useState<DrawerTab>("evidence");
  const activeTab = controlledActiveTab ?? internalActiveTab;
  const setActiveTab = (tab: DrawerTab) => {
    setInternalActiveTab(tab);
    onActiveTabChange?.(tab);
  };
  const tabRefs = useRef<Record<DrawerTab, HTMLButtonElement | null>>({ evidence: null, review: null });
  const wasOpen = useRef(false);

  useEffect(() => {
    if (result && !wasOpen.current) window.setTimeout(() => tabRefs.current[activeTab]?.focus(), 0);
    wasOpen.current = Boolean(result);
  }, [activeTab, result]);
  useEffect(() => {
    if (!result) return;
    const handleEscape = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose, result]);

  if (!result) return null;

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, current: DrawerTab) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs: DrawerTab[] = ["evidence", "review"];
    const index = tabs.indexOf(current);
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    setActiveTab(tabs[nextIndex]);
    tabRefs.current[tabs[nextIndex]]?.focus();
  };

  const singapore = result.rule_evaluations.filter(isSingaporeEvaluation);
  const acdCandidates = result.identity.acd_candidates;
  const crossReferences = result.rule_evaluations.flatMap((evaluation) => evaluation.evidence.cross_references)
    .filter((reference, index, all) => all.findIndex((item) => item.cross_reference_id === reference.cross_reference_id) === index);
  const counterparts = result.rule_evaluations.flatMap((evaluation) => evaluation.evidence.acd_counterpart_rules)
    .filter((counterpart, index, all) => all.findIndex((item) => item.rule_id === counterpart.rule_id) === index);
  const sourceIdentifiers = [
    ...acdCandidates.flatMap((candidate) => candidate.cas_numbers.map((cas) => ({ cas, section: candidate.regulatory_section }))),
    ...counterparts.flatMap((counterpart) => counterpart.cas_numbers.map((cas) => ({ cas, section: counterpart.regulatory_section }))),
  ].filter((value, index, all) => all.findIndex((item) => item.cas === value.cas && item.section === value.section) === index);
  const explanation = result.review_explanation;
  const regulatoryFactLabel = result.review_types.includes("identity_review") ? "Source" : "Rule";
  const declaredFunctions = result.submitted_ingredient.regulated_functions ?? [];
  const functionEvaluations = result.function_evaluations ?? [];
  const conditionEvaluations = result.condition_evaluations ?? [];
  const warningRequirements = result.warning_requirements ?? [];
  const incompleteFunctions = result.incomplete_positive_list_checks ?? [];
  const reviewerStatus = reviewDataState === "available" && reviewItem
    ? reviewStatusPresentation[reviewItem.review_status ?? "not_reviewed"].label
    : reviewDataState === "loading" ? "Review loading"
      : reviewDataState === "unavailable" ? "Review unavailable"
        : reviewDataState === "not_applicable" ? "Not saved" : "No review status";
  const canEditReview = reviewDataState === "available" && Boolean(reviewItem && onReviewStatusChange && onAddReviewerNote && onAddFollowUp && onToggleFollowUp && onNoteDraftChange && onFollowUpDraftChange);

  return <>
    <button className="drawer-backdrop" onClick={onClose} aria-label="Close evidence" />
    <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-label="Regulatory evidence">
      <header className="evidence-drawer-header">
        <div className="evidence-drawer-topline">
          <div><span>Row {result.submitted_row_number}</span><h2>{displayIngredientName(result)}</h2></div>
          <div className="evidence-drawer-controls">
            <button className="icon-button" type="button" disabled={!hasPrevious} onClick={onPrevious} aria-label="Previous result"><ChevronLeft size={17} /></button>
            <button className="icon-button" type="button" disabled={!hasNext} onClick={onNext} aria-label="Next result"><ChevronRight size={17} /></button>
            <button className="icon-button" type="button" onClick={onClose} aria-label="Close evidence drawer"><X size={18} /></button>
          </div>
        </div>
        <div className="evidence-drawer-badges"><FindingBadge finding={result.primary_finding} /><span className={`review-status-badge ${reviewItem?.review_status ? reviewStatusPresentation[reviewItem.review_status].className : ""}`}>{reviewerStatus}</span></div>
        <div className="evidence-drawer-tabs" role="tablist" aria-label="Result details">
          <button ref={(node) => { tabRefs.current.evidence = node; }} id="drawer-tab-evidence" role="tab" type="button" aria-selected={activeTab === "evidence"} aria-controls="drawer-panel-evidence" tabIndex={activeTab === "evidence" ? 0 : -1} onClick={() => setActiveTab("evidence")} onKeyDown={(event) => handleTabKeyDown(event, "evidence")}>Regulatory Evidence</button>
          <button ref={(node) => { tabRefs.current.review = node; }} id="drawer-tab-review" role="tab" type="button" aria-selected={activeTab === "review"} aria-controls="drawer-panel-review" tabIndex={activeTab === "review" ? 0 : -1} onClick={() => setActiveTab("review")} onKeyDown={(event) => handleTabKeyDown(event, "review")}>Review</button>
        </div>
      </header>

      <div id="drawer-panel-evidence" className="evidence-drawer-body" role="tabpanel" aria-labelledby="drawer-tab-evidence" hidden={activeTab !== "evidence"}>
        <section>
          <h3 className="drawer-title">Screening result</h3>
          <div className="metadata-grid mt-3">
            <span>Identity resolution</span><strong>{readableCode(result.identity.status)}</strong>
            <span>Match method</span><strong>{result.identity.match_methods.map(matchMethodLabel).join(", ") || "—"}</strong>
            <span>Confirmed findings</span><strong>{result.confirmed_findings.map(readableCode).join(", ") || "—"}</strong>
            <span>Professional review</span><strong>{result.review_required ? "Required" : "Not required by this result"}</strong>
          </div>
          {result.review_required && <div className="review-panel mt-4">
            <h4>{explanation?.title ?? "This result needs checking"}</h4>
            <p>{explanation?.summary ?? "Regulens could not confirm one part of this result."}</p>
            {explanation?.what_to_check && <div className="review-check"><span>What to check</span><p>{explanation.what_to_check}</p></div>}
            {(explanation?.submitted_fact || explanation?.regulatory_fact) && <div className="review-facts">
              {explanation.submitted_fact && <div><span>Submitted</span><strong>{explanation.submitted_fact}</strong></div>}
              {explanation.regulatory_fact && <div><span>{regulatoryFactLabel}</span><strong>{explanation.regulatory_fact}</strong></div>}
            </div>}
          </div>}
        </section>

        <section>
          <h3 className="drawer-title">Submitted and resolved identity</h3>
          <div className="metadata-grid mt-3">
            <span>Submitted name</span><strong>{result.submitted_ingredient.name}</strong>
            <span>Resolved display name</span><strong>{displayIngredientName(result)}</strong>
            <span>Submitted CAS</span><strong>{result.submitted_ingredient.cas_number ?? "—"}</strong>
            <span>Concentration</span><strong>{formatConcentration(result.submitted_ingredient.concentration)}</strong>
            <span>Product context</span><strong>{result.submitted_product_context ?? "—"}</strong>
            <span>Declared functions</span><strong>{declaredFunctions.length ? declaredFunctions.map(readableCode).join(", ") : "None declared"}</strong>
            {result.submitted_ingredient.concentration && <><span>Preparation stage</span><strong>{preparationStageLabel(result.submitted_ingredient.concentration.preparation_stage)}</strong><span>Basis</span><strong>{basisLabel(result.submitted_ingredient.concentration.basis)}</strong></>}
          </div>
          {sourceIdentifiers.length > 0 && <div className="source-identifier"><span>Source-backed identifier</span>{sourceIdentifiers.map((identifier) => <div key={`${identifier.cas}-${identifier.section}`}>CAS {identifier.cas} · {identifier.section.replace("Part 1", "").trim()}</div>)}</div>}
        </section>

        <section>
          <h3 className="drawer-title">Applicable Singapore rules</h3>
          {singapore.length === 0 ? <p className="drawer-empty">No Singapore rule evaluated.</p> : singapore.map((evaluation) => <article className="evidence-card" key={evaluation.rule_id}>
            <div className="evidence-card-heading"><div><strong>{evaluation.evidence.regulatory_section}</strong><span>Reference {evaluation.evidence.reference_number}{regulationLabel(evaluation) ? ` · ${regulationLabel(evaluation)}` : ""}</span></div><span className="quiet-badge">{readableCode(evaluation.evaluation_status)}</span></div>
            <div className="metadata-grid mt-4">
              <span>Source substance</span><strong className="whitespace-pre-wrap">{evaluation.evidence.substance_name}</strong>
              <span>Category</span><strong>{evaluation.evidence.regulatory_category ? readableCode(evaluation.evidence.regulatory_category) : "—"}</strong>
              <span>Regulated function</span><strong>{evaluation.evidence.permitted_function ? readableCode(evaluation.evidence.permitted_function) : "—"}</strong>
              <span>Applicable context</span><strong>{evaluation.evidence.product_context ?? "—"}</strong>
              <span>Limit</span><strong>{formatRuleConcentration(evaluation.evidence.concentration)}</strong>
              {evaluation.evidence.concentration && <><span>Comparator</span><strong>{comparatorLabel(evaluation.evidence.concentration.comparator)}</strong><span>Basis</span><strong>{basisLabel(evaluation.evidence.concentration.basis)}</strong><span>Stage</span><strong>{preparationStageLabel(evaluation.evidence.concentration.preparation_stage)}</strong></>}
            </div>
            <ConcentrationComparison evaluation={evaluation} />
            {evaluation.evidence.other_conditions && <p className="evidence-condition"><strong>Other requirements:</strong> {evaluation.evidence.other_conditions}</p>}
            {evaluation.evidence.required_warning && <p className="evidence-condition"><strong>Required warning:</strong> {evaluation.evidence.required_warning}</p>}
            <div className="source-wording-label">Original source wording</div><blockquote className="source-quote">{evaluation.evidence.source_text}</blockquote>
          </article>)}
          {conditionEvaluations.length > 0 && <div className="condition-list"><h4>Use-condition checks</h4>{conditionEvaluations.map((condition, index) => <div className="evidence-card" key={`${condition.rule_id}-${condition.condition_type}-${index}`}><div className="evidence-card-heading"><strong>{readableCode(condition.condition_type)}</strong><span className="quiet-badge">{readableCode(condition.status)}</span></div><p>{condition.source_text}</p>{condition.reason && <small>{readableCode(condition.reason)}</small>}</div>)}</div>}
        </section>

        {singapore.length > 0 && <section><h3 className="drawer-title">Accepted source evidence</h3>{singapore.map((evaluation) => <SourceEvidence key={evaluation.rule_id} evaluation={evaluation} source={sources.find((source) => source.source_document === evaluation.evidence.source_document)} />)}</section>}

        <section>
          <h3 className="drawer-title">Warnings and bounded scope</h3>
          <div className="evidence-card">
            <div className="metadata-grid"><span>Singapore sections searched</span><strong>{result.searched_singapore_parts.join(", ") || "—"}</strong><span>Positive-list checks</span><strong>{functionEvaluations.length ? functionEvaluations.map((item) => `${readableCode(item.regulated_function)}: ${readableCode(item.status)}`).join(" · ") : "No regulated function declared"}</strong></div>
            {incompleteFunctions.length > 0 && <p className="scope-warning">Incomplete because the active dataset or submitted facts do not support: {incompleteFunctions.map(readableCode).join(", ")}.</p>}
            <p>{result.scope_note}</p>
          </div>
          {warningRequirements.length > 0 && <div className="warning-list"><h4>Label warning requirements</h4><p>These are source requirements for future label review. Formulation screening does not confirm that a label contains them.</p>{warningRequirements.map((warning, index) => <article className="evidence-card" key={`${warning.rule_id}-${index}`}><div className="evidence-card-heading"><strong>{warning.source_reference}</strong><span className="quiet-badge">{readableCode(warning.applicability)}</span></div><p>{warning.warning_text}</p>{warning.trigger_text && <small>Applies when: {warning.trigger_text}</small>}</article>)}</div>}
          {result.searched_regulatory_sections.length > 0 && <ul className="scope-check-list">{result.searched_regulatory_sections.map((section) => <li key={section}><span aria-hidden="true">✓</span>{section} searched</li>)}</ul>}
          {result.identity.catalogue_identity && result.rule_evaluations.length === 0 && <p className="no-listing">No scoped regulatory listing identified</p>}
        </section>

        {(crossReferences.length > 0 || counterparts.length > 0 || acdCandidates.length > 0) && <details className="acd-details"><summary>ACD comparison</summary><div className="drawer-details-body">
          {crossReferences.map((reference) => <article key={reference.cross_reference_id}>{reference.material_difference && <p className="scope-warning">Material Singapore–ACD difference requires professional review.</p>}<div className="evidence-card-heading"><strong>ACD reference {reference.reference_number}</strong><span className="quiet-badge">{readableCode(reference.comparison_status)}</span></div>{comparisonRows(reference).length > 0 && <div className="acd-comparison-table"><div className="acd-comparison-head"><span>Field</span><span>ASEAN ACD</span><span>Singapore</span></div>{comparisonRows(reference).map((row, index) => <div className="acd-comparison-row" key={`${row.field}-${index}`}><strong>{row.field}</strong><span>{row.acd}</span><span>{row.singapore}</span></div>)}</div>}{reference.review_reasons.map((reason) => <p className="scope-warning" key={reason}>{reviewReasonLabel(reason)}</p>)}</article>)}
          {counterparts.map((counterpart) => <article className="counterpart-rule" key={counterpart.rule_id}><strong>{counterpart.regulatory_section} · Ref {counterpart.reference_number}</strong><p>{counterpart.source_version}</p><p>{counterpart.source_text}</p><a className="source-link" href={counterpart.source_url} target="_blank" rel="noreferrer">View ACD source <ExternalLink size={14} /></a></article>)}
        </div></details>}

        {(inputProvenance || result.identity.catalogue_identity) && <details className="acd-details"><summary>Identity and input provenance</summary><div className="drawer-details-body">
          {inputProvenance && <section><h3 className="drawer-title">Input provenance</h3><div className="metadata-grid"><span>Source file</span><strong>{inputProvenance.filename}</strong><span>Source rows</span><strong>{inputProvenance.sourceRows.join(", ")}</strong><span>Original value</span><strong>{inputProvenance.originalValue ?? "—"}</strong><span>Interpreted as</span><strong>{inputProvenance.interpretedValue}</strong><span>Interpretation</span><strong>{inputProvenance.confirmedByUser ? "Confirmed by user" : inputProvenance.method.replaceAll("_", " ")}</strong>{inputProvenance.sourceMetadata.map((item, index) => <span key={`${item.source_row}-${item.source_column_index}-${index}`} className="contents"><span>{item.source_column}</span><strong>{item.source_value}</strong></span>)}</div></section>}
          {result.identity.catalogue_identity && <section><h3 className="drawer-title">Ingredient identity catalogue</h3><div className="metadata-grid"><span>Recognised name</span><strong>{result.identity.catalogue_identity.canonical_name}</strong><span>Identity source</span><strong>{result.identity.catalogue_identity.source_name}</strong><span>EU entry</span><strong>{result.identity.catalogue_identity.source_entries.join(", ")}</strong><span>Source page</span><strong>{result.identity.catalogue_identity.source_pages.join(", ")}</strong></div><p className="catalogue-caveat">Catalogue recognition confirms the ingredient name only. It does not establish Singapore permission, safety, or regulatory status.</p><IdentitySourceEvidence identity={result.identity.catalogue_identity} /></section>}
        </div></details>}

        {result.review_required && <details className="acd-details"><summary>Technical provenance</summary><div className="metadata-grid drawer-details-body"><span>Review types</span><strong>{result.review_types.join(", ")}</strong><span>Review reasons</span><strong>{result.review_reasons.join(", ")}</strong><span>Explanation source</span><strong>{explanation?.source ?? "unavailable"}</strong><span>Explanation model</span><strong>{explanation?.source === "model" ? (explanationMetadata?.actual_model ?? explanationMetadata?.configured_model ?? "—") : "Deterministic fallback"}</strong></div><p className="technical-note">Review guidance explains the existing deterministic result. Regulatory evidence and rule evaluation remain the source of truth.</p></details>}
      </div>

      <div id="drawer-panel-review" className="evidence-drawer-body review-drawer-panel" role="tabpanel" aria-labelledby="drawer-tab-review" hidden={activeTab !== "review"}>
        <div className="immutable-finding-notice"><strong>Regulatory result remains unchanged</strong><p>Reviewer status, notes, and follow-ups document the human review workflow. They do not alter the deterministic screening result.</p></div>
        {reviewDataState === "loading" && <div className="review-state-message" role="status"><strong>Loading reviewer workflow</strong><p>Regulatory evidence remains available while saved review information loads.</p></div>}
        {reviewDataState === "unavailable" && <div className="review-state-message"><strong>Review information unavailable</strong><p>You can continue inspecting the regulatory result, but reviewer actions are temporarily unavailable.</p></div>}
        {reviewDataState === "not_applicable" && <div className="review-state-message"><strong>Not saved in a case</strong><p>Save this screening in a case to record reviewer status, notes, and follow-ups.</p></div>}
        {reviewDataState === "available" && !reviewItem && <div className="review-state-message"><strong>No reviewer item for this result</strong><p>This result remains available for evidence inspection.</p></div>}
        {canEditReview && reviewItem && onReviewStatusChange && onAddReviewerNote && onAddFollowUp && onToggleFollowUp && onNoteDraftChange && onFollowUpDraftChange && <ReviewerWorkspace reviewItem={reviewItem} notes={reviewerNotes} followUps={followUps} statusWriteState={statusWriteState} noteWriteState={noteWriteState} followUpWriteState={followUpWriteState} pendingReviewStatus={pendingReviewStatus} followUpWriteStates={followUpWriteStates} noteDraft={noteDraft} followUpDraft={followUpDraft} onNoteDraftChange={onNoteDraftChange} onFollowUpDraftChange={onFollowUpDraftChange} onStatusChange={onReviewStatusChange} onAddNote={onAddReviewerNote} onAddFollowUp={onAddFollowUp} onToggleFollowUp={onToggleFollowUp} />}
      </div>
    </aside>
  </>;
}

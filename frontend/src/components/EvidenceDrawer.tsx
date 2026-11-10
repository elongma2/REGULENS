import { ChevronLeft, ChevronRight, ExternalLink, Maximize2, Minimize2, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { FindingBadge } from "./FindingBadge";
import { IdentitySourceEvidence } from "./IdentitySourceEvidence";
import { ReviewerWorkspace } from "./ReviewerWorkspace";
import { SourceEvidence } from "./SourceEvidence";
import {
  basisLabel, comparisonRows, displayIngredientName, formatRuleConcentration,
  matchMethodLabel, preparationStageLabel, readableCode,
} from "../lib/presentation";
import {
  formatConcentration, ingredientReviewIssues, ingredientScreeningDisposition,
  isSingaporeEvaluation, regulationLabel,
} from "../lib/screening";
import { reviewStatusPresentation, type WriteState } from "../lib/reviewPresentation";
import {
  contributionDocumentReference,
  contributionSourceName,
  findAssemblyAggregate,
  formatAssemblyQuantity,
  formatEvaluatedAssemblyQuantity,
} from "../lib/assembly";
import type { InputProvenance } from "../types/agent";
import type { FollowUp, ReviewDataState, ReviewerNote, ReviewItem, ReviewStatus } from "../types/review";
import type { IngredientResult, RuleEvaluation, ScreeningResponse, SourceSnapshot } from "../types/screening";

export type DrawerTab = "evidence" | "review";

function concentrationComparison(evaluation: RuleEvaluation) {
  const submitted = evaluation.submitted_concentration;
  const limit = evaluation.evidence.concentration;
  if (evaluation.evaluation_status !== "deterministic" ||
    !["restriction_exceeded", "restriction_within_limit"].includes(evaluation.finding ?? "") ||
    !submitted || (submitted.concentration_type ?? "exact") !== "exact" || typeof submitted.value !== "number" ||
    !limit || typeof limit.value !== "number" || submitted.unit !== limit.unit ||
    submitted.basis !== (limit.basis ?? null) || submitted.preparation_stage !== limit.preparation_stage ||
    limit.comparator !== "less_than_or_equal") return null;
  return { submitted, limit, difference: submitted.value - limit.value };
}

function ConcentrationComparison({ evaluation }: { evaluation: RuleEvaluation }) {
  const comparison = concentrationComparison(evaluation);
  if (!comparison) return null;
  return <div className="comparison-panel mt-3" aria-label="Concentration comparison">
    <div><span>Evaluated concentration</span><strong>{formatConcentration(comparison.submitted)}</strong></div>
    <div><span>Singapore maximum</span><strong>{formatRuleConcentration(comparison.limit)}</strong></div>
    <div className="comparison-total"><span>Difference</span><strong className={comparison.difference > 0 ? "text-red-700" : "text-emerald-700"}>{comparison.difference > 0 ? "+" : ""}{comparison.difference.toFixed(2)} {comparison.limit.unit === "percent" ? "percentage points" : comparison.limit.unit}</strong></div>
  </div>;
}

function uniqueText(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  return values.flatMap((value) => {
    const normalized = value?.trim().replace(/\s+/g, " ");
    const key = normalized?.toLocaleLowerCase().replace(/\.$/, "");
    if (!normalized || !key || seen.has(key)) return [];
    seen.add(key);
    return [normalized];
  });
}

export function EvidenceDrawer({
  result, sources, inputProvenance, explanationMetadata, assemblyCalculationSnapshot, reviewItem, reviewerNotes = [], followUps = [],
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
  assemblyCalculationSnapshot?: Record<string, unknown> | null;
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
  const [isWide, setIsWide] = useState(false);
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
  const singaporeGroups = Array.from(singapore.reduce((groups, evaluation) => {
    const key = `${evaluation.evidence.regulatory_section}:${evaluation.evidence.reference_number}`;
    groups.set(key, [...(groups.get(key) ?? []), evaluation]);
    return groups;
  }, new Map<string, RuleEvaluation[]>()).values());
  const acdCandidates = result.identity.acd_candidates;
  const crossReferences = result.rule_evaluations.flatMap((evaluation) => evaluation.evidence.cross_references)
    .filter((reference, index, all) => all.findIndex((item) => item.cross_reference_id === reference.cross_reference_id) === index);
  const counterparts = result.rule_evaluations.flatMap((evaluation) => evaluation.evidence.acd_counterpart_rules)
    .filter((counterpart, index, all) => all.findIndex((item) => item.rule_id === counterpart.rule_id) === index);
  const sourceIdentifiers = [
    ...acdCandidates.flatMap((candidate) => candidate.cas_numbers.map((cas) => ({ cas, section: candidate.regulatory_section }))),
    ...counterparts.flatMap((counterpart) => counterpart.cas_numbers.map((cas) => ({ cas, section: counterpart.regulatory_section }))),
  ].filter((value, index, all) => all.findIndex((item) => item.cas === value.cas && item.section === value.section) === index);
  const reviewIssues = ingredientReviewIssues(result);
  const legacyAssemblyOnly = (result.review_issues ?? []).some((issue) => issue.code === "assembly_incomplete")
    && reviewIssues.length === 0;
  const storedExplanation = result.review_explanation;
  const explanation = legacyAssemblyOnly && (
    storedExplanation?.items?.every((item) => item.issue_code === "assembly_incomplete")
    || storedExplanation?.title?.toLocaleLowerCase().includes("assembly incomplete")
  ) ? undefined : storedExplanation;
  const leadingIssue = reviewIssues[0];
  const screeningDisposition = ingredientScreeningDisposition(result);
  const explanationItems = explanation?.items ?? [];
  const reviewerActions = uniqueText(
    explanation?.reviewer_actions?.length
      ? explanation.reviewer_actions
      : [...explanationItems.map((item) => item.what_to_check), explanation?.what_to_check, leadingIssue?.reviewer_action],
  );
  const declaredFunctions = result.submitted_ingredient.regulated_functions ?? [];
  const functionEvaluations = result.function_evaluations ?? [];
  const conditionEvaluations = (result.condition_evaluations ?? []).filter((condition, index, all) =>
    all.findIndex((candidate) => candidate.condition_type === condition.condition_type
      && candidate.status === condition.status
      && candidate.source_text === condition.source_text
      && candidate.reason === condition.reason) === index);
  const warningRequirements = result.warning_requirements ?? [];
  const assemblyAggregate = findAssemblyAggregate(assemblyCalculationSnapshot, result);
  const finalConcentration = assemblyAggregate
    ? formatEvaluatedAssemblyQuantity(assemblyAggregate) ?? formatAssemblyQuantity(assemblyAggregate.aggregate_quantity)
    : formatConcentration(result.submitted_ingredient.concentration);
  const singaporeLimits = uniqueText(singapore.map((evaluation) =>
    evaluation.evidence.concentration ? formatRuleConcentration(evaluation.evidence.concentration) : null));
  const nextAction = reviewerActions[0] ?? (
    result.primary_finding === "restriction_exceeded" || result.primary_finding === "permitted_use_condition_not_met"
      ? "Reformulate to meet the applicable Singapore requirement, then screen the updated formulation."
      : "No regulatory action is required for this ingredient within the evaluated scope."
  );
  const incompleteFunctions = result.incomplete_positive_list_checks ?? [];
  const reviewerStatus = reviewDataState === "available" && reviewItem
    ? reviewStatusPresentation[reviewItem.review_status ?? "not_reviewed"].label
    : reviewDataState === "loading" ? "Review loading"
      : reviewDataState === "unavailable" ? "Review unavailable"
        : reviewDataState === "not_applicable" ? "Not saved" : "No review status";
  const canEditReview = reviewDataState === "available" && Boolean(reviewItem && onReviewStatusChange && onAddReviewerNote && onAddFollowUp && onToggleFollowUp && onNoteDraftChange && onFollowUpDraftChange);

  return <>
    <button className="drawer-backdrop" onClick={onClose} aria-label="Close evidence" />
    <aside className={`evidence-drawer${isWide ? " is-wide" : ""}`} role="dialog" aria-modal="true" aria-label="Regulatory evidence">
      <header className="evidence-drawer-header">
        <div className="evidence-drawer-topline">
          <div><span>Row {result.submitted_row_number}</span><h2>{displayIngredientName(result)}</h2></div>
          <div className="evidence-drawer-controls">
            <button className="icon-button" type="button" disabled={!hasPrevious} onClick={onPrevious} aria-label="Previous result"><ChevronLeft size={17} /></button>
            <button className="icon-button" type="button" disabled={!hasNext} onClick={onNext} aria-label="Next result"><ChevronRight size={17} /></button>
            <button className="icon-button drawer-width-toggle" type="button" aria-pressed={isWide} onClick={() => setIsWide((current) => !current)} aria-label={isWide ? "Restore drawer width" : "Widen evidence drawer"}>{isWide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>
            <button className="icon-button" type="button" onClick={onClose} aria-label="Close evidence drawer"><X size={18} /></button>
          </div>
        </div>
        <div className="evidence-drawer-badges"><FindingBadge finding={result.primary_finding} screeningDisposition={screeningDisposition} /><span className={`review-status-badge ${reviewItem?.review_status ? reviewStatusPresentation[reviewItem.review_status].className : ""}`}>{reviewerStatus}</span></div>
        <div className="evidence-drawer-tabs" role="tablist" aria-label="Result details">
          <button ref={(node) => { tabRefs.current.evidence = node; }} id="drawer-tab-evidence" role="tab" type="button" aria-selected={activeTab === "evidence"} aria-controls="drawer-panel-evidence" tabIndex={activeTab === "evidence" ? 0 : -1} onClick={() => setActiveTab("evidence")} onKeyDown={(event) => handleTabKeyDown(event, "evidence")}>Regulatory Evidence</button>
          <button ref={(node) => { tabRefs.current.review = node; }} id="drawer-tab-review" role="tab" type="button" aria-selected={activeTab === "review"} aria-controls="drawer-panel-review" tabIndex={activeTab === "review" ? 0 : -1} onClick={() => setActiveTab("review")} onKeyDown={(event) => handleTabKeyDown(event, "review")}>Review</button>
        </div>
      </header>

      <div id="drawer-panel-evidence" className="evidence-drawer-body" role="tabpanel" aria-labelledby="drawer-tab-evidence" hidden={activeTab !== "evidence"}>
        <section>
          <h3 className="drawer-title">Regulatory assessment</h3>
          <div className="finding-summary-grid mt-3">
            <div><span>Ingredient</span><strong>{displayIngredientName(result)}</strong></div>
            <div><span>Combined final concentration</span><strong>{finalConcentration}</strong></div>
            <div><span>Applicable Singapore limit</span><strong>{singaporeLimits.join(" · ") || "No concentration limit identified"}</strong></div>
            <div><span>Outcome</span><strong>{readableCode(result.primary_finding)}</strong></div>
          </div>
          {(result.review_required || leadingIssue) && <div className="review-panel mt-4">
            <h4>{explanation?.title ?? (leadingIssue ? readableCode(leadingIssue.code) : "This result needs checking")}</h4>
            <p>{explanation?.summary ?? leadingIssue?.message ?? "Regulens could not confirm one part of this result."}</p>
          </div>}
          <div className="next-action"><span>Next action</span><strong>{nextAction}</strong></div>
        </section>

        {(assemblyAggregate || explanation?.calculation_context) && <details className="acd-details"><summary>View calculation</summary><div className="drawer-details-body">
          {assemblyAggregate && <>
            <div className="metadata-grid"><span>Finished-product amount</span><strong>{formatEvaluatedAssemblyQuantity(assemblyAggregate) ?? formatAssemblyQuantity(assemblyAggregate.aggregate_quantity)}</strong><span>Contributions</span><strong>{assemblyAggregate.contributions?.length ?? 0}</strong></div>
            {(assemblyAggregate.contributions ?? []).map((contribution, index) => {
              const documentReference = contributionDocumentReference(assemblyCalculationSnapshot, contribution);
              const isSupplierContribution = Boolean(contribution.source_material_id);
              return <article className="evidence-card" key={contribution.contribution_id ?? `${contribution.source_material_id}-${index}`}>
                <div className="evidence-card-heading"><strong>{contributionSourceName(assemblyCalculationSnapshot, contribution)}</strong><span className="quiet-badge">{formatAssemblyQuantity(contribution.finished_product_quantity)}</span></div>
                <div className="metadata-grid mt-3">
                  {isSupplierContribution ? <><span>Inside supplier material</span><strong>{formatAssemblyQuantity(contribution.composition_quantity)}</strong><span>Material used</span><strong>{formatAssemblyQuantity(contribution.material_usage)}</strong></> : null}
                  <span>Calculation</span><strong>{contribution.calculation_formula || "Direct finished-product value"}</strong>
                  <span>Source document</span><strong>{documentReference ?? "Source unavailable"}</strong>
                </div>
                {(contribution.source_evidence ?? []).map((evidence, evidenceIndex) => evidence.source_snippet ? <p className="technical-note" key={`${evidence.page ?? "page"}-${evidenceIndex}`}>{evidence.page ? `Page ${evidence.page}: ` : ""}{evidence.source_snippet}</p> : null)}
              </article>;
            })}
          </>}
          {!assemblyAggregate && explanation?.calculation_context && <div className="review-calculation" aria-label="Supplier calculation used for screening">
            <div className="review-calculation-heading"><span>Combined finished-product concentration</span><strong>{explanation.calculation_context.finished_product_concentration}</strong></div>
            {explanation.calculation_context.contributions.map((contribution, index) => <div className="review-calculation-contribution" key={`${contribution.trade_material ?? "material"}-${index}`}><strong>{contribution.trade_material ?? "Supplier material"}</strong><div><span>Inside supplier material</span><b>{contribution.supplier_concentration}</b><span>Material used</span><b>{contribution.material_usage}</b><span>Finished-product contribution</span><b>{contribution.finished_product_contribution}</b></div><small>{contribution.calculation_formula}{contribution.source_pages.length ? ` · Source page${contribution.source_pages.length > 1 ? "s" : ""} ${contribution.source_pages.join(", ")}` : ""}</small></div>)}
          </div>}
        </div></details>}

        <section>
          <h3 className="drawer-title">Applicable Singapore rules</h3>
          {singaporeGroups.length === 0 ? <p className="drawer-empty">No Singapore rule evaluated.</p> : singaporeGroups.map((evaluations) => {
            const primary = evaluations[0];
            const conditions = uniqueText(evaluations.map((evaluation) => evaluation.evidence.other_conditions));
            const warnings = uniqueText(evaluations.map((evaluation) => evaluation.evidence.required_warning));
            const sourceWordings = uniqueText(evaluations.map((evaluation) => evaluation.evidence.source_text));
            const footnotes = evaluations.flatMap((evaluation) => evaluation.evidence.footnotes ?? []).filter((footnote, index, all) => all.findIndex((candidate) => candidate.footnote_number === footnote.footnote_number && candidate.source_text === footnote.source_text) === index);
            return <article className="evidence-card" key={`${primary.evidence.regulatory_section}-${primary.evidence.reference_number}`}>
              <div className="evidence-card-heading"><div><strong>{primary.evidence.regulatory_section}</strong><span>Reference {primary.evidence.reference_number}{regulationLabel(primary) ? ` · ${regulationLabel(primary)}` : ""}</span></div><span className="quiet-badge">{evaluations.length > 1 ? `${evaluations.length} conditions` : readableCode(primary.evaluation_status)}</span></div>
              <div className="metadata-grid mt-4"><span>Source substance</span><strong className="whitespace-pre-wrap">{primary.evidence.substance_name}</strong><span>Category</span><strong>{primary.evidence.regulatory_category ? readableCode(primary.evidence.regulatory_category) : "—"}</strong><span>Regulated function</span><strong>{primary.evidence.permitted_function ? readableCode(primary.evidence.permitted_function) : "—"}</strong></div>
              <div className="rule-branch-list">{evaluations.map((evaluation) => <div key={evaluation.rule_id}><span>{evaluation.evidence.product_context ?? "General condition"}</span><strong>{formatRuleConcentration(evaluation.evidence.concentration)}</strong><small>{readableCode(evaluation.evaluation_status)}</small><ConcentrationComparison evaluation={evaluation} /></div>)}</div>
              {conditions.map((condition) => <p className="evidence-condition" key={condition}><strong>Other requirement:</strong> {condition}</p>)}
              {warnings.map((warning) => <p className="evidence-condition" key={warning}><strong>Required warning:</strong> {warning}</p>)}
              {footnotes.length > 0 && <div className="evidence-condition"><strong>Linked footnotes:</strong>{footnotes.map((footnote, index) => <p key={`${footnote.footnote_number ?? "note"}-${index}`}>{footnote.footnote_number ? `${footnote.footnote_number}. ` : ""}{footnote.source_text}</p>)}</div>}
              <details className="rule-source-wording"><summary>Original source wording</summary>{sourceWordings.map((wording) => <blockquote className="source-quote" key={wording}>{wording}</blockquote>)}</details>
            </article>;
          })}
          {conditionEvaluations.length > 0 && <div className="condition-list"><h4>Use-condition checks</h4>{conditionEvaluations.map((condition, index) => <div className="evidence-card" key={`${condition.rule_id}-${condition.condition_type}-${index}`}><div className="evidence-card-heading"><strong>{readableCode(condition.condition_type)}</strong><span className="quiet-badge">{readableCode(condition.status)}</span></div><p>{condition.source_text}</p>{condition.reason && <small>{readableCode(condition.reason)}</small>}</div>)}</div>}
        </section>

        {singaporeGroups.length > 0 && <section><h3 className="drawer-title">Accepted source evidence</h3>{singaporeGroups.map((evaluations) => { const evaluation = evaluations[0]; return <SourceEvidence key={`${evaluation.evidence.regulatory_section}-${evaluation.evidence.reference_number}`} evaluation={evaluation} source={sources.find((source) => source.source_document === evaluation.evidence.source_document)} />; })}</section>}

        <details className="acd-details"><summary>Advanced details</summary><div className="drawer-details-body">
          <div className="metadata-grid">
            <span>Submitted name</span><strong>{result.submitted_ingredient.name}</strong>
            <span>Resolved identity</span><strong>{displayIngredientName(result)}</strong>
            <span>Submitted CAS</span><strong>{result.submitted_ingredient.cas_number ?? "—"}</strong>
            <span>Identity matching</span><strong>{result.identity.match_methods.map(matchMethodLabel).join(", ") || "—"}</strong>
            <span>Identity outcome</span><strong>{result.identity.identity_outcome ? readableCode(result.identity.identity_outcome) : readableCode(result.identity.status)}</strong>
            <span>Screening coverage</span><strong>{screeningDisposition ? readableCode(screeningDisposition) : "Historical result"}</strong>
            <span>Product context</span><strong>{result.submitted_product_context ?? "—"}</strong>
            <span>Declared functions</span><strong>{declaredFunctions.length ? declaredFunctions.map(readableCode).join(", ") : "None declared"}</strong>
            {result.submitted_ingredient.concentration && <><span>Preparation stage</span><strong>{preparationStageLabel(result.submitted_ingredient.concentration.preparation_stage)}</strong><span>Basis</span><strong>{basisLabel(result.submitted_ingredient.concentration.basis)}</strong></>}
            <span>Screening datasets</span><strong>{result.searched_singapore_parts.join(", ") || "—"}</strong>
            <span>Positive-list checks</span><strong>{functionEvaluations.length ? functionEvaluations.map((item) => `${readableCode(item.regulated_function)}: ${readableCode(item.status)}`).join(" · ") : "No regulated function declared"}</strong>
            {explanation?.submitted_fact && <><span>Submitted assessment fact</span><strong>{explanation.submitted_fact}</strong></>}
            {explanation?.regulatory_fact && <><span>{result.review_types.includes("identity_review") ? "Source" : "Rule"}</span><strong>{explanation.regulatory_fact}</strong></>}
          </div>
          {sourceIdentifiers.length > 0 && <div className="source-identifier"><span>Source-backed identifier</span>{sourceIdentifiers.map((identifier) => <div key={`${identifier.cas}-${identifier.section}`}>CAS {identifier.cas} · {identifier.section.replace("Part 1", "").trim()}</div>)}</div>}
          <div className="evidence-card mt-4">
            {incompleteFunctions.length > 0 && <p className="scope-warning">Incomplete because the active dataset or submitted facts do not support: {incompleteFunctions.map(readableCode).join(", ")}.</p>}
            <p>{result.scope_note}</p>
          </div>
          {warningRequirements.length > 0 && <div className="warning-list"><h4>Label warning requirements</h4><p>These are source requirements for future label review. Formulation screening does not confirm that a label contains them.</p>{warningRequirements.map((warning, index) => <article className="evidence-card" key={`${warning.rule_id}-${index}`}><div className="evidence-card-heading"><strong>{warning.source_reference}</strong><span className="quiet-badge">{readableCode(warning.applicability)}</span></div><p>{warning.warning_text}</p>{warning.trigger_text && <small>Applies when: {warning.trigger_text}</small>}</article>)}</div>}
          {result.searched_regulatory_sections.length > 0 && <ul className="scope-check-list">{result.searched_regulatory_sections.map((section) => <li key={section}><span aria-hidden="true">✓</span>{section} searched</li>)}</ul>}
          {result.identity.catalogue_identity && result.rule_evaluations.length === 0 && <p className="no-listing">No scoped regulatory listing identified</p>}
        </div></details>

        {(crossReferences.length > 0 || counterparts.length > 0 || acdCandidates.length > 0) && <details className="acd-details"><summary>ACD comparison</summary><div className="drawer-details-body">
          {crossReferences.map((reference) => <article key={reference.cross_reference_id}>
            <div className="evidence-card-heading"><strong>ACD reference {reference.reference_number}</strong><span className="quiet-badge">{readableCode(reference.semantic_comparison_status ?? reference.comparison_status)}</span></div>
            <p>{reference.comparison_summary ?? "Comparison has not yet been semantically validated."}</p>
            {reference.verification_needed && <p className="scope-warning"><strong>Verification needed:</strong> {reference.verification_needed}</p>}
            {comparisonRows(reference).length > 0 && <div className="acd-comparison-table"><div className="acd-comparison-head"><span>Requirement</span><span>ASEAN ACD</span><span>Singapore</span></div>{comparisonRows(reference).map((row, index) => <div className="acd-comparison-row" key={`${row.field}-${index}`}><strong>{row.field}</strong><span>{row.acd}</span><span>{row.singapore}</span></div>)}</div>}
            {(reference.comparison_citations ?? []).length > 0 && <div className="comparison-citations">{reference.comparison_citations?.map((citation) => citation.source_url ? <a className="source-link" href={citation.source_url} target="_blank" rel="noreferrer" key={`${citation.jurisdiction}-${citation.rule_id}`}>{citation.jurisdiction}: {citation.section} Ref {citation.reference_number}{citation.source_pages.length ? `, page ${citation.source_pages.join(", ")}` : ""} <ExternalLink size={13} /></a> : null)}</div>}
          </article>)}
          {counterparts.map((counterpart) => <article className="counterpart-rule" key={counterpart.rule_id}><strong>{counterpart.regulatory_section} · Ref {counterpart.reference_number}</strong><p>{counterpart.source_version}</p><p>{counterpart.source_text}</p><a className="source-link" href={counterpart.source_url} target="_blank" rel="noreferrer">View ACD source <ExternalLink size={14} /></a></article>)}
        </div></details>}

        {(inputProvenance || result.identity.catalogue_identity) && <details className="acd-details"><summary>Identity and input provenance</summary><div className="drawer-details-body">
          {inputProvenance && <section><h3 className="drawer-title">Input provenance</h3><div className="metadata-grid"><span>Source file</span><strong>{inputProvenance.filename}</strong><span>Source rows</span><strong>{inputProvenance.sourceRows.join(", ")}</strong><span>Original value</span><strong>{inputProvenance.originalValue ?? "—"}</strong><span>Interpreted as</span><strong>{inputProvenance.interpretedValue}</strong><span>Interpretation</span><strong>{inputProvenance.confirmedByUser ? "Confirmed by user" : inputProvenance.method.replaceAll("_", " ")}</strong>{inputProvenance.sourceMetadata.map((item, index) => <span key={`${item.source_row}-${item.source_column_index}-${index}`} className="contents"><span>{item.source_column}</span><strong>{item.source_value}</strong></span>)}</div></section>}
          {result.identity.catalogue_identity && <section><h3 className="drawer-title">Ingredient identity catalogue</h3><div className="metadata-grid"><span>Recognised name</span><strong>{result.identity.catalogue_identity.canonical_name}</strong><span>Identity source</span><strong>{result.identity.catalogue_identity.source_name}</strong><span>EU entry</span><strong>{result.identity.catalogue_identity.source_entries.join(", ")}</strong><span>Source page</span><strong>{result.identity.catalogue_identity.source_pages.join(", ")}</strong></div><p className="catalogue-caveat">Catalogue recognition confirms the ingredient name only. It does not establish Singapore permission, safety, or regulatory status.</p><IdentitySourceEvidence identity={result.identity.catalogue_identity} /></section>}
        </div></details>}

        {result.review_required && <details className="acd-details"><summary>Technical provenance</summary><div className="metadata-grid drawer-details-body"><span>Review types</span><strong>{result.review_types.join(", ")}</strong><span>Review reasons</span><strong>{result.review_reasons.join(", ")}</strong><span>Structured issue codes</span><strong>{reviewIssues.map((item) => item.code).join(", ") || "Historical result"}</strong><span>Reviewer action</span><strong>{result.identity.reviewer_action ?? "—"}</strong><span>Applicable records</span><strong>{result.identity.applicable_regulatory_record_ids?.join(", ") || "—"}</strong>{result.identity.identifier_evidence?.map((item) => <span className="contents" key={`${item.identifier_type}-${item.submitted_value ?? "none"}`}><span>{readableCode(item.identifier_type)} lookup</span><strong>{readableCode(item.outcome)}{item.submitted_value ? ` · ${item.submitted_value}` : ""}</strong></span>)}<span>Explanation source</span><strong>{explanation?.source ?? "unavailable"}</strong><span>Explanation model</span><strong>{explanation?.source === "model" ? (explanationMetadata?.actual_model ?? explanationMetadata?.configured_model ?? "—") : "Deterministic fallback"}</strong></div><p className="technical-note">Review guidance explains the existing deterministic result. Regulatory evidence and rule evaluation remain the source of truth.</p></details>}
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

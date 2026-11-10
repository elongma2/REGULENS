import { GitMerge, LoaderCircle, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { displayIngredientName } from "../lib/presentation";
import { reviewStatusPresentation } from "../lib/reviewPresentation";
import { findingPresentation, requiresAttention } from "../lib/screening";
import type { ReviewDataState, ReviewItem, ReviewStatus } from "../types/review";
import type { Finding, ScreeningResponse } from "../types/screening";
import { ResultsTable } from "./ResultsTable";
import { ScreeningSummary } from "./ScreeningSummary";

type FilterPreset = "all" | "attention" | "not_reviewed";

const assemblyIssueLabels: Record<string, string> = {
  material_usage_missing: "How much of a raw material is used in the finished product is missing.",
  incomplete_supplier_disclosure: "A supplier file may list only some ingredients in the raw material.",
  composition_statement_conflict: "More than one file describes the same raw material; the current file must be chosen.",
  document_association_unconfirmed: "A raw material has not been connected to the correct supplier file.",
  unresolved_raw_material: "A raw material could not be confidently identified.",
  constituent_concentration_missing: "An ingredient amount could not be read from a supplier file.",
  constituent_identity_unresolved: "An ingredient name or CAS number still needs confirmation.",
  incompatible_quantity_basis: "Two amounts use units that cannot be combined safely.",
  invalid_concentration_bound: "A supplier percentage or range is invalid, including reversed or out-of-bounds values.",
  impossible_composition_total: "The ingredient percentages in a supplier file add up to more than 100%.",
  unverified_identity_aggregation: "Matching ingredient amounts could not be safely added together.",
};

export function ScreeningResultsPanel({
  response,
  selectedRow,
  onSelect,
  reviewItems = [],
  reviewDataState = "not_applicable",
  openFindingFollowUps = 0,
  onVisibleRowsChange,
  onIdentitySuggestionDecision,
  identityDecisionBusy = false,
}: {
  response: ScreeningResponse;
  selectedRow: number | null;
  onSelect: (row: number) => void;
  reviewItems?: ReviewItem[];
  reviewDataState?: ReviewDataState;
  openFindingFollowUps?: number;
  onVisibleRowsChange?: (rowNumbers: number[]) => void;
  onIdentitySuggestionDecision?: (
    targetId: string,
    decision: "confirmed" | "rejected",
  ) => Promise<void>;
  identityDecisionBusy?: boolean;
}) {
  const [preset, setPreset] = useState<FilterPreset>("all");
  const [query, setQuery] = useState("");
  const [finding, setFinding] = useState<Finding | "all">("all");
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus | "all">("all");
  const [identityDecisionTarget, setIdentityDecisionTarget] = useState<string | null>(null);
  const [identityDecisionError, setIdentityDecisionError] = useState<string | null>(null);
  const reviewAvailable = reviewDataState === "available";
  const assemblyScope = response.formulation.assembly_scope;
  const coverageCodes = assemblyScope?.coverage_limitation_codes ?? (
    assemblyScope?.issue_codes.includes("incomplete_supplier_disclosure")
      ? ["incomplete_supplier_disclosure"] : []
  );
  const actionCodes = assemblyScope?.action_required_codes ?? assemblyScope?.issue_codes.filter(
    (code) => !coverageCodes.includes(code),
  ) ?? [];
  const reviewByRow = useMemo(() => new Map(reviewItems.map((item) => [item.submitted_row_number, item])), [reviewItems]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const hasFilters = preset !== "all" || normalizedQuery.length > 0 || finding !== "all" || reviewStatus !== "all";
  const pendingIdentitySuggestions = response.ingredient_results.filter(
    (result) => result.submitted_ingredient.identity_suggestion?.status === "pending",
  );

  const decideIdentity = async (targetId: string, decision: "confirmed" | "rejected") => {
    if (!onIdentitySuggestionDecision || identityDecisionBusy) return;
    setIdentityDecisionTarget(targetId);
    setIdentityDecisionError(null);
    try {
      await onIdentitySuggestionDecision(targetId, decision);
    } catch (caught) {
      setIdentityDecisionError(caught instanceof Error ? caught.message : "The identity decision could not be saved.");
    } finally {
      setIdentityDecisionTarget(null);
    }
  };

  useEffect(() => {
    if (reviewDataState !== "unavailable" && reviewDataState !== "not_applicable") return;
    if (preset === "not_reviewed") setPreset("all");
    if (reviewStatus !== "all") setReviewStatus("all");
  }, [preset, reviewDataState, reviewStatus]);

  const filtered = useMemo(() => response.ingredient_results.filter((result) => {
    const item = reviewByRow.get(result.submitted_row_number);
    if (preset === "attention" && !requiresAttention(result)) return false;
    if (preset === "not_reviewed" && (!item || (item.review_status !== null && item.review_status !== "not_reviewed"))) return false;
    if (finding !== "all" && result.primary_finding !== finding) return false;
    if (reviewStatus === "not_reviewed" && (!item || (item.review_status !== null && item.review_status !== "not_reviewed"))) return false;
    if (reviewStatus !== "all" && reviewStatus !== "not_reviewed" && item?.review_status !== reviewStatus) return false;
    if (!normalizedQuery) return true;
    const searchableNames = [
      result.submitted_ingredient.name,
      displayIngredientName(result),
      ...result.identity.singapore_candidates.map((candidate) => candidate.original_substance_name),
      ...result.identity.acd_candidates.map((candidate) => candidate.original_substance_name),
      result.identity.catalogue_identity?.canonical_name,
    ];
    return searchableNames.some((value) => value?.toLocaleLowerCase().includes(normalizedQuery));
  }), [finding, normalizedQuery, preset, response.ingredient_results, reviewByRow, reviewStatus]);

  const visibleRows = useMemo(
    () => filtered.map((result) => result.submitted_row_number),
    [filtered],
  );

  useEffect(() => {
    onVisibleRowsChange?.(visibleRows);
  }, [onVisibleRowsChange, visibleRows]);

  const clearFilters = () => {
    setPreset("all");
    setQuery("");
    setFinding("all");
    setReviewStatus("all");
  };

  return (
    <div className="screening-results-panel">
      <ScreeningSummary
        summary={response.summary}
        results={response.ingredient_results}
        reviewItems={reviewItems}
        reviewDataState={reviewDataState}
        openFindingFollowUps={openFindingFollowUps}
      />

      {pendingIdentitySuggestions.length > 0 && (
        <section className="identity-suggestion-review" aria-labelledby="identity-suggestion-title">
          <div className="identity-suggestion-heading">
            <GitMerge size={17} aria-hidden="true" />
            <div>
              <h3 id="identity-suggestion-title">Possible ingredient name match</h3>
              <p>AI noticed a likely naming equivalent. It remains unidentified unless you confirm it.</p>
            </div>
          </div>
          <div className="identity-suggestion-list">
            {pendingIdentitySuggestions.map((result) => {
              const suggestion = result.submitted_ingredient.identity_suggestion!;
              const pending = identityDecisionTarget === suggestion.target_id;
              return <article key={suggestion.target_id} className="identity-suggestion-item">
                <div>
                  <strong>{suggestion.original_name}</strong>
                  <span aria-hidden="true">→</span>
                  <strong>{suggestion.canonical_name}</strong>
                  <p>{suggestion.explanation}</p>
                </div>
                <div className="identity-suggestion-actions">
                  <button className="primary-button" type="button" disabled={!onIdentitySuggestionDecision || identityDecisionBusy} aria-busy={pending} onClick={() => void decideIdentity(suggestion.target_id, "confirmed")}>
                    {pending ? <LoaderCircle className="button-spinner" size={15} aria-hidden="true" /> : null}
                    Confirm match
                  </button>
                  <button className="secondary-button" type="button" disabled={!onIdentitySuggestionDecision || identityDecisionBusy} onClick={() => void decideIdentity(suggestion.target_id, "rejected")}>Keep unidentified</button>
                </div>
              </article>;
            })}
          </div>
          {!onIdentitySuggestionDecision && <p className="identity-suggestion-history">This is a historical screening snapshot. Open the current screening to decide.</p>}
          {identityDecisionError && <p className="identity-suggestion-error" role="alert">{identityDecisionError}</p>}
        </section>
      )}

      {assemblyScope && assemblyScope.completeness !== "complete" && (
        <div className="assembly-scope-warning" role="status">
          <strong>{assemblyScope.completeness === "blocked"
            ? "Some ingredients could not be calculated"
            : actionCodes.length
              ? "Some inputs still need attention"
              : "Screening reflects the supplier information provided"}</strong>
          <p>
            {assemblyScope.completeness === "blocked"
              ? "The results below do not include the raw materials with missing or conflicting information."
              : actionCodes.length
                ? "Regulens screened the supported information. Remaining inputs and supplier-file limitations prevent a complete product conclusion."
                : "Regulens screened the disclosed ingredients and amounts. Partial or proprietary supplier disclosure remains a coverage limitation, not a request to invent missing values."}
          </p>
          {(actionCodes.length > 0 || coverageCodes.length > 0) && <details>
            <summary>View screening coverage</summary>
            <ul>
              {Array.from(new Set(actionCodes)).map((code) => <li key={`action:${code}`}>{assemblyIssueLabels[code] ?? "More information is needed before this ingredient can be fully checked."}</li>)}
              {Array.from(new Set(coverageCodes)).map((code) => <li key={`coverage:${code}`}>{assemblyIssueLabels[code] ?? "The supplier evidence limits the scope of this screening."}</li>)}
            </ul>
          </details>}
        </div>
      )}

      {reviewDataState === "unavailable" && (
        <p className="review-data-notice" role="status">
          Review information is unavailable. Regulatory findings and evidence remain available.
        </p>
      )}

      <div id="screening-results-controls" className="results-toolbar" aria-label="Result controls" tabIndex={-1}>
        <div className="results-filter-presets" role="group" aria-label="Result filter presets">
          <button type="button" className={preset === "all" ? "is-active" : ""} aria-pressed={preset === "all"} onClick={() => setPreset("all")}>All results</button>
          <button type="button" className={preset === "attention" ? "is-active" : ""} aria-pressed={preset === "attention"} onClick={() => setPreset("attention")}>Needs attention</button>
          <button type="button" className={preset === "not_reviewed" ? "is-active" : ""} aria-pressed={preset === "not_reviewed"} disabled={!reviewAvailable} title={reviewAvailable ? undefined : "Available for saved screenings when review information has loaded"} onClick={() => setPreset("not_reviewed")}>Not reviewed</button>
        </div>

        <label className="results-search">
          <span className="sr-only">Search ingredients</span>
          <Search size={14} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search ingredients" />
        </label>

        <label>Regulatory result<select aria-label="Regulatory result" value={finding} onChange={(event) => setFinding(event.target.value as Finding | "all")}><option value="all">All result types</option>{Object.entries(findingPresentation).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select></label>
        {reviewAvailable && <label>Review status<select aria-label="Review status" value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value as ReviewStatus | "all")}><option value="all">All statuses</option>{Object.entries(reviewStatusPresentation).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}</select></label>}

        <span className="results-count">{filtered.length} result{filtered.length === 1 ? "" : "s"}</span>
      </div>

      {filtered.length > 0 ? (
        <ResultsTable results={filtered} reviewItems={reviewItems} showReviewStatus={reviewAvailable} selectedRow={selectedRow} onSelect={onSelect} assemblyCalculationSnapshot={response.formulation.assembly_calculation_snapshot} />
      ) : (
        <div className="results-empty-state">
          <strong>No results match these filters.</strong>
          <p>The screening results are unchanged. Clear the filters to see every ingredient.</p>
          {hasFilters && <button className="secondary-button" type="button" onClick={clearFilters}><X size={14} aria-hidden="true" /> Clear filters</button>}
        </div>
      )}

      <details className="screening-scope-disclosure">
        <summary>Screening scope and dataset</summary>
        <div>
          <p>Rules checked: {Array.from(new Set(response.ingredient_results.flatMap((result) => result.searched_singapore_parts))).join(", ") || "No Singapore section searched"}. Colourant, preservative and UV-filter checks require their use to be confirmed when it affects the rule.</p>
          <p>These are ingredient-level screening results for professional review, not a formulation-level compliance conclusion.</p>
          <p>Dataset {response.dataset.dataset_version} · Accepted baseline {response.dataset.accepted_baseline_sha256}</p>
        </div>
      </details>
    </div>
  );
}

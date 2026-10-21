import { Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { displayIngredientName } from "../lib/presentation";
import { reviewStatusPresentation } from "../lib/reviewPresentation";
import { findingPresentation, requiresAttention } from "../lib/screening";
import type { ReviewDataState, ReviewItem, ReviewStatus } from "../types/review";
import type { Finding, ScreeningResponse } from "../types/screening";
import { ResultsTable } from "./ResultsTable";
import { ScreeningSummary } from "./ScreeningSummary";

type FilterPreset = "all" | "attention" | "not_reviewed";

export function ScreeningResultsPanel({
  response,
  selectedRow,
  onSelect,
  reviewItems = [],
  reviewDataState = "not_applicable",
  openFindingFollowUps = 0,
  onVisibleRowsChange,
}: {
  response: ScreeningResponse;
  selectedRow: number | null;
  onSelect: (row: number) => void;
  reviewItems?: ReviewItem[];
  reviewDataState?: ReviewDataState;
  openFindingFollowUps?: number;
  onVisibleRowsChange?: (rowNumbers: number[]) => void;
}) {
  const [preset, setPreset] = useState<FilterPreset>("all");
  const [query, setQuery] = useState("");
  const [finding, setFinding] = useState<Finding | "all">("all");
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus | "all">("all");
  const reviewAvailable = reviewDataState === "available";
  const reviewByRow = useMemo(() => new Map(reviewItems.map((item) => [item.submitted_row_number, item])), [reviewItems]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const hasFilters = preset !== "all" || normalizedQuery.length > 0 || finding !== "all" || reviewStatus !== "all";

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
        <ResultsTable results={filtered} reviewItems={reviewItems} showReviewStatus={reviewAvailable} selectedRow={selectedRow} onSelect={onSelect} />
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
          <p>Screening scope: {Array.from(new Set(response.ingredient_results.flatMap((result) => result.searched_singapore_parts))).join(", ") || "No Singapore section searched"}. Positive-list checks require a declared regulated function.</p>
          <p>These are ingredient-level screening results for professional review, not a formulation-level compliance conclusion.</p>
          <p>Dataset {response.dataset.dataset_version} · Accepted baseline {response.dataset.accepted_baseline_sha256}</p>
        </div>
      </details>
    </div>
  );
}

import { requiresAttention } from "../lib/screening";
import type { ReviewDataState, ReviewItem } from "../types/review";
import type { FormulationSummary, IngredientResult } from "../types/screening";

export function ScreeningSummary({
  summary,
  results,
  reviewItems,
  reviewDataState,
  openFindingFollowUps,
}: {
  summary: FormulationSummary;
  results: IngredientResult[];
  reviewItems: ReviewItem[];
  reviewDataState: ReviewDataState;
  openFindingFollowUps: number;
}) {
  const attentionCount = results.filter(requiresAttention).length;
  const reviewsRemaining = reviewItems.filter(
    (item) => item.requires_attention && item.review_status !== "reviewed",
  ).length;
  const workflowMessage = reviewDataState === "loading"
    ? "Loading reviewer workflow"
    : reviewDataState === "not_applicable"
      ? "Reviewer workflow not saved in a case"
      : "Reviewer workflow information unavailable";

  return (
    <section className="screening-summary" aria-labelledby="summary-heading">
      <h2 id="summary-heading" className="sr-only">Screening summary</h2>
      <dl className="screening-summary-line">
        <div><dd>{summary.ingredients_submitted}</dd><dt>ingredients screened</dt></div>
        <div className="is-attention"><dd>{attentionCount}</dd><dt>ingredient results need attention</dt></div>
        <div><dd>{summary.total_unresolved_identities}</dd><dt>ingredient identities unresolved</dt></div>
        {reviewDataState === "available" ? (
          <>
            <div><dd>{reviewsRemaining}</dd><dt>reviews remaining</dt></div>
            <div><dd>{openFindingFollowUps}</dd><dt>open finding follow-ups</dt></div>
          </>
        ) : (
          <div className="screening-workflow-state"><dt>Reviewer workflow</dt><dd>{workflowMessage}</dd></div>
        )}
      </dl>

      {summary.duplicate_row_groups.length > 0 ? (
        <p className="screening-summary-note">
          Duplicate submitted rows retained: {summary.duplicate_row_groups.map((rows) => rows.join(", ")).join(" · ")}
        </p>
      ) : null}
    </section>
  );
}

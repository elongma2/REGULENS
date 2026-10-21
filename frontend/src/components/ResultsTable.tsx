import { ChevronRight } from "lucide-react";
import { FindingBadge } from "./FindingBadge";
import { formatConcentration, regulationLabel, supportingSingaporeEvaluations } from "../lib/screening";
import { displayIngredientName } from "../lib/presentation";
import { reviewStatusPresentation } from "../lib/reviewPresentation";
import type { IngredientResult } from "../types/screening";
import type { ReviewItem } from "../types/review";

function RuleCell({ result }: { result: IngredientResult }) {
  const evaluations = supportingSingaporeEvaluations(result);
  if (!evaluations.length) return <span className="text-slate-400">—</span>;
  const evaluation = evaluations[0];
  const regulation = regulationLabel(evaluation);
  return (
    <div className="leading-5">
      <div>{evaluation.evidence.regulatory_section}</div>
      <div className="text-xs text-slate-500">
        Ref {evaluation.evidence.reference_number}{regulation ? ` · ${regulation}` : ""}
        {evaluations.length > 1 ? ` · +${evaluations.length - 1}` : ""}
      </div>
    </div>
  );
}

export function ResultsTable({
  results,
  selectedRow,
  onSelect,
  reviewItems = [],
  showReviewStatus = false,
}: {
  results: IngredientResult[];
  selectedRow: number | null;
  onSelect: (row: number) => void;
  reviewItems?: ReviewItem[];
  showReviewStatus?: boolean;
}) {
  const reviewByRow = new Map(reviewItems.map((item) => [item.submitted_row_number, item]));
  return (
    <section className="results-table-shell" aria-label="Ingredient screening results">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/80 text-xs font-medium text-slate-500">
              <th className="px-4 py-3">Ingredient</th>
              <th className="px-4 py-3">Submitted concentration</th>
              <th className="px-4 py-3">Result</th>
              <th className="px-4 py-3">Rule</th>
              {showReviewStatus && <th className="px-4 py-3">Review status</th>}
              <th className="w-12 px-4 py-3"><span className="sr-only">Evidence</span></th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => {
              const selected = selectedRow === result.submitted_row_number;
              const reviewItem = reviewByRow.get(result.submitted_row_number);
              return (
                <tr
                  key={result.submitted_row_number}
                  id={`screening-result-row-${result.submitted_row_number}`}
                  className={`result-row ${selected ? "result-row-selected" : ""}`}
                  tabIndex={0}
                  aria-selected={selected}
                  onClick={() => onSelect(result.submitted_row_number)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(result.submitted_row_number);
                    }
                  }}
                >
                  <td className="px-4 py-3.5">
                    <div className="font-medium text-slate-900">{displayIngredientName(result)}</div>
                    <div className="mt-0.5 text-xs text-slate-400">Row {result.submitted_row_number}</div>
                  </td>
                  <td className="px-4 py-3.5 text-slate-700">{formatConcentration(result.submitted_ingredient.concentration)}</td>
                  <td className="px-4 py-3.5"><FindingBadge finding={result.primary_finding} /></td>
                  <td className="px-4 py-3.5 text-slate-700"><RuleCell result={result} /></td>
                  {showReviewStatus && <td className="px-4 py-3.5">{reviewItem?.review_status ? <span className={`review-status-badge ${reviewStatusPresentation[reviewItem.review_status].className}`}>{reviewStatusPresentation[reviewItem.review_status].label}</span> : <span className="text-slate-400">—</span>}</td>}
                  <td className="px-4 py-3.5 text-slate-400"><ChevronRight size={16} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

import { findingPresentation } from "../lib/screening";
import type { Finding } from "../types/screening";

export function FindingBadge({
  finding,
  screeningDisposition,
}: {
  finding: Finding;
  screeningDisposition?: "fully_evaluated" | "evaluated_with_identity_review" | "partially_evaluated" | "not_evaluated_identity_unresolved";
}) {
  if (
    screeningDisposition === "partially_evaluated"
    && ["no_issue_identified_within_scoped_rules", "restriction_within_limit", "permitted_use_within_conditions"].includes(finding)
  ) {
    return <span className="inline-flex items-center gap-2 border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
      Partially evaluated
    </span>;
  }
  if (screeningDisposition === "not_evaluated_identity_unresolved") {
    return <span className="inline-flex items-center gap-2 border border-slate-200 bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
      <span className="h-1.5 w-1.5 rounded-full bg-slate-500" aria-hidden="true" />
      Not evaluated
    </span>;
  }
  const presentation = findingPresentation[finding];
  return (
    <span className={`inline-flex items-center gap-2 border px-2 py-1 text-xs font-medium ${presentation.tone}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${presentation.dot}`} aria-hidden="true" />
      {presentation.label}
    </span>
  );
}

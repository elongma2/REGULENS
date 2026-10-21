import type { Finding, IngredientResult, RuleEvaluation } from "../types/screening";

export const findingPresentation: Record<Finding, { label: string; tone: string; dot: string }> = {
  prohibited_substance_identified: {
    label: "Prohibited-list substance identified",
    tone: "text-red-700 bg-red-50 border-red-200",
    dot: "bg-red-600",
  },
  restriction_exceeded: {
    label: "Limit exceeded",
    tone: "text-red-700 bg-red-50 border-red-200",
    dot: "bg-red-600",
  },
  restriction_within_limit: {
    label: "Within limit",
    tone: "text-emerald-700 bg-emerald-50 border-emerald-200",
    dot: "bg-emerald-600",
  },
  permitted_use_within_conditions: {
    label: "Listed use conditions met",
    tone: "text-emerald-700 bg-emerald-50 border-emerald-200",
    dot: "bg-emerald-600",
  },
  permitted_use_condition_not_met: {
    label: "Listed use condition not met",
    tone: "text-red-700 bg-red-50 border-red-200",
    dot: "bg-red-600",
  },
  regulated_function_not_permitted: {
    label: "Regulated function not listed",
    tone: "text-red-700 bg-red-50 border-red-200",
    dot: "bg-red-600",
  },
  professional_review_required: {
    label: "Needs human review",
    tone: "text-amber-800 bg-amber-50 border-amber-200",
    dot: "bg-amber-500",
  },
  information_missing: {
    label: "Information missing",
    tone: "text-amber-800 bg-amber-50 border-amber-200",
    dot: "bg-amber-500",
  },
  identity_unresolved: {
    label: "Identity unresolved",
    tone: "text-slate-700 bg-slate-100 border-slate-200",
    dot: "bg-slate-500",
  },
  no_issue_identified_within_scoped_rules: {
    label: "No issue identified within scoped rules",
    tone: "text-emerald-700 bg-emerald-50 border-emerald-200",
    dot: "bg-emerald-600",
  },
};

export const adversePrimaryFindings = new Set<Finding>([
  "prohibited_substance_identified",
  "restriction_exceeded",
  "permitted_use_condition_not_met",
  "regulated_function_not_permitted",
  "professional_review_required",
  "information_missing",
  "identity_unresolved",
]);

export function requiresAttention(result: IngredientResult): boolean {
  return adversePrimaryFindings.has(result.primary_finding)
    || result.review_required
    || result.identity.status !== "resolved"
    || (result.incomplete_positive_list_checks?.length ?? 0) > 0;
}

const confirmedPrecedence: Finding[] = [
  "prohibited_substance_identified",
  "restriction_exceeded",
  "regulated_function_not_permitted",
  "permitted_use_condition_not_met",
  "restriction_within_limit",
  "permitted_use_within_conditions",
  "information_missing",
  "no_issue_identified_within_scoped_rules",
];

export function isSingaporeEvaluation(evaluation: RuleEvaluation): boolean {
  return [
    "Third Schedule Part I",
    "Third Schedule Part II",
    "Third Schedule Part III",
    "Third Schedule Part IV",
    "Third Schedule Part V",
  ].includes(
    evaluation.evidence.regulatory_section,
  );
}

export function supportingSingaporeEvaluations(result: IngredientResult): RuleEvaluation[] {
  const singapore = result.rule_evaluations.filter(isSingaporeEvaluation);
  const primary = singapore.filter(
    (evaluation) => evaluation.evaluation_status !== "withheld" && evaluation.finding === result.primary_finding,
  );
  if (primary.length) return primary;

  for (const finding of confirmedPrecedence) {
    if (!result.confirmed_findings.includes(finding)) continue;
    const matches = singapore.filter(
      (evaluation) => evaluation.evaluation_status === "deterministic" && evaluation.finding === finding,
    );
    if (matches.length) return matches;
  }
  return [];
}

export function regulationLabel(evaluation: RuleEvaluation): string | null {
  const provision = evaluation.evidence.regulation_6_provisions.find(
    (item) => ["1", "2", "3", "4", "5"].includes(item.paragraph),
  );
  return provision ? `Regulation 6(${provision.paragraph})` : null;
}

export function formatConcentration(value: IngredientResult["submitted_ingredient"]["concentration"]): string {
  if (!value) return "—";
  const unit = value.unit === "percent" ? "%" : ` ${value.unit}`;
  return `${value.value}${unit}`;
}

export function humanizeCode(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

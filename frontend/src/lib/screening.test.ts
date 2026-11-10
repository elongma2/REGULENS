import { describe, expect, it } from "vitest";
import { findingPresentation, formatConcentration, ingredientReviewIssues, ingredientScreeningDisposition, isSingaporeEvaluation, requiresAttention, supportingSingaporeEvaluations } from "./screening";
import { baseResult, evidence } from "../test/fixtures";

describe("Singapore table rule selection", () => {
  it("selects the Singapore evaluation supporting the displayed primary finding", () => {
    const result = baseResult(1, "Example");
    result.primary_finding = "restriction_exceeded";
    result.confirmed_findings = ["restriction_exceeded"];
    result.rule_evaluations = [
      {
        rule_id: "unrelated",
        evaluation_status: "deterministic",
        finding: "restriction_within_limit",
        reasons: [], submitted_concentration: null,
        evidence: evidence("II", "4", "Example"),
      },
      {
        rule_id: "supporting",
        evaluation_status: "deterministic",
        finding: "restriction_exceeded",
        reasons: [], submitted_concentration: null,
        evidence: evidence("II", "5", "Example"),
      },
    ];
    expect(supportingSingaporeEvaluations(result).map((item) => item.rule_id)).toEqual(["supporting"]);
  });

  it("recognises Parts III-V and presents the new bounded findings", () => {
    const partV = evidence("II", "3", "Homosalate");
    partV.regulatory_section = "Third Schedule Part V";
    expect(isSingaporeEvaluation({ rule_id: "uv", evaluation_status: "deterministic", finding: "permitted_use_within_conditions", reasons: [], submitted_concentration: null, evidence: partV })).toBe(true);
    expect(findingPresentation.regulated_function_not_permitted.label).toBe("Regulated function not listed");
    expect(findingPresentation.permitted_use_condition_not_met.label).toBe("Listed use condition not met");
  });

  it("does not use ACD identity-only or withheld evaluations as Singapore table rules", () => {
    const result = baseResult(1, "Example");
    result.primary_finding = "professional_review_required";
    result.review_required = true;
    const withheld = evidence("II", "5", "Example");
    const acdOnly = evidence("II", "342", "BHT");
    acdOnly.regulatory_section = "Annex III Part 1";
    result.rule_evaluations = [
      {
        rule_id: "acd-only",
        evaluation_status: "identity_evidence",
        finding: "professional_review_required",
        reasons: ["acd_only"],
        submitted_concentration: null,
        evidence: acdOnly,
      },
      {
        rule_id: "withheld",
        evaluation_status: "withheld",
        finding: null,
        reasons: ["manual_review_required"],
        submitted_concentration: null,
        evidence: withheld,
      },
    ];
    expect(supportingSingaporeEvaluations(result)).toEqual([]);
  });
});

describe("requiresAttention", () => {
  it("uses regulatory findings independently of persisted review data", () => {
    const adverse = baseResult(1, "Adverse");
    adverse.primary_finding = "restriction_exceeded";
    expect(requiresAttention(adverse)).toBe(true);

    const explicitReview = baseResult(2, "Review");
    explicitReview.review_required = true;
    expect(requiresAttention(explicitReview)).toBe(true);

    const unresolved = baseResult(3, "Unresolved");
    unresolved.identity.status = "ambiguous";
    expect(requiresAttention(unresolved)).toBe(true);

    const incomplete = baseResult(4, "Incomplete");
    incomplete.incomplete_positive_list_checks = ["preservative"];
    expect(requiresAttention(incomplete)).toBe(true);

    expect(requiresAttention(baseResult(5, "Quiet result"))).toBe(false);
  });
});

describe("legacy assembly-result presentation", () => {
  it("keeps formulation coverage out of an otherwise complete ingredient result", () => {
    const result = baseResult(1, "GLYCERIN");
    result.screening_disposition = "partially_evaluated";
    result.review_issues = [{
      code: "assembly_incomplete",
      severity: "information_missing",
      scope: "screening",
      message: "Another material is incomplete.",
      reviewer_action: "Review the formulation.",
      rule_id: null,
      source_reference: null,
      missing_facts: [],
      related_rule_ids: [],
      related_constituent_references: [],
    }];

    expect(ingredientScreeningDisposition(result)).toBe("fully_evaluated");
    expect(ingredientReviewIssues(result)).toEqual([]);
    expect(findingPresentation.no_issue_identified_within_scoped_rules.label).toBe("No applicable restriction identified");
  });
});

describe("formatConcentration", () => {
  const semantics = { unit: "percent" as const, basis: null, preparation_stage: "finished_product" as const };

  it("preserves exact, ranged, bounded, approximate, and undisclosed quantities", () => {
    expect(formatConcentration({ ...semantics, concentration_type: "exact", value: 0.6, original_text: "(6%) x (10%) / 100" })).toBe("0.60%");
    expect(formatConcentration({ ...semantics, concentration_type: "range", value: null, lower_bound: 0.04, upper_bound: 0.2 })).toBe("0.04–0.20%");
    expect(formatConcentration({ ...semantics, concentration_type: "upper_bound", value: null, upper_bound: 1, upper_inclusive: true })).toBe("≤1.00%");
    expect(formatConcentration({ ...semantics, concentration_type: "lower_bound", value: null, lower_bound: 0.1, lower_inclusive: true })).toBe("≥0.10%");
    expect(formatConcentration({ ...semantics, concentration_type: "approximate", value: 0.5 })).toBe("≈0.50%");
    expect(formatConcentration({ ...semantics, concentration_type: "range", value: null, lower_bound: 0.278, upper_bound: 0.305 })).toBe("0.28–0.31%");
    expect(formatConcentration({ ...semantics, concentration_type: "unknown", value: null, unit: null, preparation_stage: null })).toBe("Unknown");
  });
});

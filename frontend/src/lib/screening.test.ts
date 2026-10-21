import { describe, expect, it } from "vitest";
import { findingPresentation, isSingaporeEvaluation, requiresAttention, supportingSingaporeEvaluations } from "./screening";
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

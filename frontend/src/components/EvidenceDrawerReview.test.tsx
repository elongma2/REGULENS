import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { baseResult, evidence } from "../test/fixtures";

function reviewResult(source: "model" | "deterministic_fallback" = "model") {
  const result = baseResult(1, "Tosylchloramide sodium");
  result.primary_finding = "professional_review_required";
  result.review_required = true;
  result.review_types = ["rule_review"];
  result.review_reasons = ["incompatible_preparation_stage"];
  result.review_explanation = {
    title: "Concentration stage needs confirmation",
    summary: "The submitted concentration is for one stage, but the rule applies at a different stage.",
    what_to_check: "Confirm the concentration at the stage stated in the rule.",
    submitted_fact: "2% · Finished product",
    regulatory_fact: "Maximum 2% · After mixing for use",
    source,
  };
  const rule = evidence("II", "5", "Tosylchloramide sodium");
  result.rule_evaluations = [{
    rule_id: rule.rule_id,
    evaluation_status: "manual_review_required",
    finding: "professional_review_required",
    reasons: ["incompatible_preparation_stage"],
    submitted_concentration: { value: 2, unit: "percent", basis: null, preparation_stage: "finished_product" },
    evidence: rule,
  }];
  return result;
}

describe("review guidance", () => {
  it("does not repeat a legacy formulation-level assembly warning on an ingredient", () => {
    const result = baseResult(1, "GLYCERIN");
    result.screening_disposition = "partially_evaluated";
    result.review_issues = [{
      code: "assembly_incomplete",
      severity: "information_missing",
      scope: "screening",
      message: "Assembly incomplete.",
      reviewer_action: "Review another supplier material.",
      rule_id: null,
      source_reference: null,
      missing_facts: [],
      related_rule_ids: [],
      related_constituent_references: [],
    }];
    result.review_explanation = {
      title: "Assembly incomplete",
      summary: "Another supplier material is incomplete.",
      what_to_check: "Review another supplier material.",
      submitted_fact: null,
      regulatory_fact: null,
      source: "deterministic_fallback",
      items: [{
        issue_code: "assembly_incomplete",
        what_happened: "Assembly incomplete.",
        why_it_matters: "Product coverage is limited.",
        what_to_check: "Review another supplier material.",
        source_references: [],
      }],
    };

    render(<EvidenceDrawer result={result} sources={[]} onClose={vi.fn()} />);

    expect(screen.getByText("No applicable restriction identified")).toBeInTheDocument();
    expect(screen.getByText("Fully evaluated")).toBeInTheDocument();
    expect(screen.queryByText("Assembly incomplete")).not.toBeInTheDocument();
    expect(screen.queryByText("Review another supplier material.")).not.toBeInTheDocument();
  });

  it("shows source-backed trade-material calculation provenance", async () => {
    const user = userEvent.setup();
    const result = baseResult(1, "GLYCERIN");
    result.submitted_ingredient.cas_number = "56-81-5";
    render(<EvidenceDrawer
      result={result}
      sources={[]}
      assemblyCalculationSnapshot={{
        source_documents: {
          "supplier-document-1": { original_filename: "AegisMix-P80.pdf", supplier_name: "Aegis Labs", trade_name: "AegisMix P80" },
        },
        materials: [{ material_id: "OPTASENSE", trade_name: "AegisMix P80", supplier_name: "Aegis Labs" }],
        aggregates: [{
          display_name: "GLYCERIN",
          cas_number: "56-81-5",
          aggregate_quantity: { kind: "exact", value: 1, unit: "percent" },
          contributions: [{
            contribution_id: "contribution-1",
            source_material_id: "OPTASENSE",
            governing_document_id: "supplier-document-1",
            composition_quantity: { kind: "exact", value: 50, unit: "percent" },
            material_usage: { kind: "exact", value: 2, unit: "percent" },
            finished_product_quantity: { kind: "exact", value: 1, unit: "percent" },
            calculation_formula: "2% × 50% = 1%",
            source_evidence: [{ page: 2, source_snippet: "Glycerin 50%" }],
          }],
        }],
      }}
      onClose={vi.fn()}
    />);
    await user.click(screen.getByText("View calculation"));
    expect(screen.getByText("AegisMix P80 · Aegis Labs")).toBeInTheDocument();
    expect(screen.getByText("2% × 50% = 1%")).toBeInTheDocument();
    expect(screen.getByText("AegisMix-P80.pdf")).toBeInTheDocument();
    expect(screen.getByText("Page 2: Glycerin 50%")).toBeInTheDocument();
  });

  it("shows deterministic supplier calculation facts in an expandable calculation", async () => {
    const user = userEvent.setup();
    const result = reviewResult("deterministic_fallback");
    result.review_explanation!.calculation_context = {
      finished_product_concentration: "0.1%",
      contributions: [{
        trade_material: "Supplier Blend X",
        supplier_concentration: "5%",
        material_usage: "2%",
        finished_product_contribution: "0.1%",
        calculation_formula: "2% × 5% ÷ 100 = 0.1%",
        source_pages: [3],
      }],
      regulatory_limits: ["Maximum 0.2% · Finished product"],
      remaining_uncertainties: ["Confirm the concentration at the stage stated in the rule."],
    };
    render(<EvidenceDrawer result={result} sources={[]} onClose={vi.fn()} />);

    await user.click(screen.getByText("View calculation"));
    expect(screen.getByLabelText("Supplier calculation used for screening")).toBeInTheDocument();
    expect(screen.getByText("Combined finished-product concentration")).toBeInTheDocument();
    expect(screen.getAllByText("0.1%")).toHaveLength(2);
    expect(screen.getByText("Supplier Blend X")).toBeInTheDocument();
    expect(screen.getByText("Inside supplier material")).toBeInTheDocument();
    expect(screen.getByText("Finished-product contribution")).toBeInTheDocument();
    expect(screen.getByText("2% × 5% ÷ 100 = 0.1% · Source page 3")).toBeInTheDocument();
  });

  it("shows plain guidance and keeps machine codes collapsed", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer
      result={reviewResult()}
      sources={[]}
      explanationMetadata={{
        configured: true,
        configured_model: "gpt-5.6-luna",
        actual_model: "gpt-5.6-luna-verified",
        status: "model",
        requested_count: 1,
        model_count: 1,
        fallback_count: 0,
        truncated_count: 0,
        usage: null,
      }}
      onClose={vi.fn()}
    />);
    expect(screen.getByText("Concentration stage needs confirmation")).toBeInTheDocument();
    expect(screen.getByText("The submitted concentration is for one stage, but the rule applies at a different stage.")).toBeInTheDocument();
    expect(screen.getByText("Confirm the concentration at the stage stated in the rule.")).toBeInTheDocument();
    expect(screen.getByText("2% · Finished product")).toBeInTheDocument();
    expect(screen.getByText("Maximum 2% · After mixing for use")).toBeInTheDocument();
    const technical = screen.getByText("Technical provenance").closest("details");
    expect(technical).not.toHaveAttribute("open");
    await user.click(screen.getByText("Technical provenance"));
    expect(technical).toHaveAttribute("open");
    expect(screen.getByText("incompatible_preparation_stage")).toBeInTheDocument();
    expect(screen.getByText("gpt-5.6-luna-verified")).toBeInTheDocument();
  });

  it("labels deterministic fallback without weakening the review", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer result={reviewResult("deterministic_fallback")} sources={[]} onClose={vi.fn()} />);
    expect(screen.getByText("Concentration stage needs confirmation")).toBeInTheDocument();
    await user.click(screen.getByText("Technical provenance"));
    expect(screen.getByText("Deterministic fallback")).toBeInTheDocument();
  });

  it("labels an identity fact as source information", () => {
    const result = reviewResult("deterministic_fallback");
    result.review_types = ["identity_review"];
    result.review_explanation = {
      title: "Name and CAS do not match",
      summary: "The ingredient name and CAS number do not point to the same ingredient.",
      what_to_check: "Confirm the correct ingredient name and CAS number.",
      submitted_fact: "Name: Aminophylline · CAS: 128-37-0",
      regulatory_fact: "Source CAS for Aminophylline: 317-34-0",
      source: "deterministic_fallback",
    };
    render(<EvidenceDrawer result={result} sources={[]} onClose={vi.fn()} />);
    expect(screen.getByText("Source")).toBeInTheDocument();
    expect(screen.getByText("Source CAS for Aminophylline: 317-34-0")).toBeInTheDocument();
  });

  it("shows the bounded identity outcome and keeps lookup evidence technical", async () => {
    const user = userEvent.setup();
    const result = reviewResult("deterministic_fallback");
    result.review_types = ["identity_review"];
    result.identity.identity_outcome = "cas_recognised_name_unverified";
    result.screening_disposition = "evaluated_with_identity_review";
    result.identity.reviewer_action = "Confirm that the submitted name belongs to the CAS-matched ingredient.";
    result.identity.applicable_regulatory_record_ids = ["sg-third-schedule-iv-29"];
    result.identity.identifier_evidence = [{
      identifier_type: "cas",
      submitted_value: "122-99-6",
      outcome: "matched",
      matched_singapore_substance_ids: ["substance-sg-third-schedule-iv-29"],
      matched_acd_substance_ids: ["substance-acd-vi-29"],
      matched_catalogue_ingredient_id: null,
    }];
    render(<EvidenceDrawer result={result} sources={[]} onClose={vi.fn()} />);
    expect(screen.getByText("Cas recognised name unverified")).toBeInTheDocument();
    expect(screen.getByText("Evaluated with identity review")).toBeInTheDocument();
    const technicalSummary = screen.getByText("Technical provenance");
    const technicalDetails = technicalSummary.closest("details");
    expect(technicalDetails).not.toHaveAttribute("open");
    await user.click(technicalSummary);
    expect(technicalDetails).toHaveAttribute("open");
    expect(screen.getByText("Matched · 122-99-6")).toBeInTheDocument();
    expect(screen.getByText("sg-third-schedule-iv-29")).toBeInTheDocument();
  });

  it("uses accessible detail tabs and exposes ad hoc review guidance", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer result={reviewResult()} sources={[]} reviewDataState="not_applicable" onClose={vi.fn()} />);

    const evidenceTab = screen.getByRole("tab", { name: "Regulatory Evidence" });
    const reviewTab = screen.getByRole("tab", { name: "Review" });
    const evidencePanel = screen.getByRole("tabpanel", { name: "Regulatory Evidence" });
    const reviewPanel = document.getElementById("drawer-panel-review")!;
    expect(evidenceTab).toHaveAttribute("aria-selected", "true");
    expect(reviewPanel).toHaveAttribute("hidden");

    await user.click(reviewTab);
    expect(reviewTab).toHaveAttribute("aria-selected", "true");
    expect(evidencePanel).toHaveAttribute("hidden");
    expect(screen.getByText("Not saved in a case")).toBeInTheDocument();
    expect(reviewPanel).not.toHaveAttribute("hidden");

    await user.keyboard("{ArrowLeft}");
    expect(evidenceTab).toHaveFocus();
    expect(evidenceTab).toHaveAttribute("aria-selected", "true");
  });

  it("navigates in filtered order through explicit previous and next handlers", async () => {
    const user = userEvent.setup();
    const onPrevious = vi.fn();
    const onNext = vi.fn();
    render(<EvidenceDrawer result={reviewResult()} sources={[]} hasPrevious={false} hasNext onPrevious={onPrevious} onNext={onNext} onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Previous result" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next result" }));
    expect(onNext).toHaveBeenCalledOnce();
    expect(onPrevious).not.toHaveBeenCalled();
  });

  it("renders one concise next action and can widen the drawer", async () => {
    const user = userEvent.setup();
    const result = reviewResult("deterministic_fallback");
    result.review_explanation = {
      title: "Additional formulation checks needed",
      summary: "The concentration branch was identified, but several source conditions still need confirmation.",
      what_to_check: "Confirm whether the product may result in inhalation exposure.",
      submitted_fact: "Approximately 2%",
      regulatory_fact: "Maximum 25%",
      source: "deterministic_fallback",
      reviewer_actions: [
        "Confirm whether Zinc Oxide (nano) is present and verify the combined concentration.",
        "Confirm whether the product may result in inhalation exposure.",
        "Confirm whether the product may result in inhalation exposure.",
        "Review the Singapore and ACD source difference.",
        "Check the nano-specific source conditions.",
      ],
      items: [
        { issue_code: "combined_limit_information_missing", what_happened: "The combined limit is incomplete.", why_it_matters: "The source limit applies to both forms.", what_to_check: "Confirm whether Zinc Oxide (nano) is present and verify the combined concentration.", source_references: ["Third Schedule Part V Ref 30"] },
        { issue_code: "applicability_fact_missing", what_happened: "Inhalation exposure is unknown.", why_it_matters: "The source restricts inhalation exposure.", what_to_check: "Confirm whether the product may result in inhalation exposure.", source_references: ["Third Schedule Part V Ref 30"] },
      ],
    };

    render(<EvidenceDrawer result={result} sources={[]} onClose={vi.fn()} />);

    expect(screen.getByText("Next action")).toBeInTheDocument();
    expect(screen.getByText("Confirm whether Zinc Oxide (nano) is present and verify the combined concentration.")).toBeInTheDocument();
    expect(screen.queryByText("Show all checks (4)")).not.toBeInTheDocument();
    expect(screen.queryByText("Why this needs review (2)")).not.toBeInTheDocument();

    const drawer = screen.getByRole("dialog", { name: "Regulatory evidence" });
    await user.click(screen.getByRole("button", { name: "Widen evidence drawer" }));
    expect(drawer).toHaveClass("is-wide");
    expect(screen.getByRole("button", { name: "Restore drawer width" })).toHaveAttribute("aria-pressed", "true");
  });

  it("groups product branches from one regulatory reference without losing either limit", () => {
    const result = reviewResult("deterministic_fallback");
    const spray = evidence("II", "10", "Octocrylene");
    spray.regulatory_section = "Third Schedule Part V";
    spray.product_context = "Propellant spray products";
    spray.concentration = { value: 9, unit: "percent", comparator: "less_than_or_equal", basis: null, preparation_stage: "finished_product" };
    const other = { ...spray, product_context: "Other products", concentration: { ...spray.concentration, value: 10 } };
    result.rule_evaluations = [
      { rule_id: `${spray.rule_id}-spray`, evaluation_status: "withheld_professional_review", finding: "professional_review_required", reasons: [], submitted_concentration: null, evidence: spray },
      { rule_id: `${spray.rule_id}-other`, evaluation_status: "withheld_professional_review", finding: "professional_review_required", reasons: [], submitted_concentration: null, evidence: other },
    ];

    render(<EvidenceDrawer result={result} sources={[]} onClose={vi.fn()} />);

    expect(screen.getByText("2 conditions")).toBeInTheDocument();
    expect(screen.getByText("Propellant spray products")).toBeInTheDocument();
    expect(screen.getByText("Other products")).toBeInTheDocument();
    expect(screen.getByText("9.00%")).toBeInTheDocument();
    expect(screen.getByText("10.00%")).toBeInTheDocument();
    expect(screen.getAllByText(/Reference 10/)).toHaveLength(1);
  });
});

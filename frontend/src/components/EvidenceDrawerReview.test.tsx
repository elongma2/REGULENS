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
});

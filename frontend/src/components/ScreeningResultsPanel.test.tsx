import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { baseResult, testResponse } from "../test/fixtures";
import type { ReviewItem } from "../types/review";
import { ScreeningResultsPanel } from "./ScreeningResultsPanel";

const reviewItem = (row: number, status: ReviewItem["review_status"]): ReviewItem => ({
  id: `review-${row}`,
  screening_run_id: "run-1",
  subject_type: "ingredient",
  subject_key: `row-${row}`,
  submitted_row_number: row,
  engine_finding: "finding",
  requires_attention: true,
  review_status: status,
  updated_by: null,
  updated_at: "2026-10-20T08:00:00Z",
  reviewed_at: null,
});

describe("ScreeningResultsPanel", () => {
  it("filters Needs attention from regulatory results in an ad hoc screening", async () => {
    const response = structuredClone(testResponse);
    response.ingredient_results.push(baseResult(4, "Quiet ingredient"));
    response.summary.ingredients_submitted = 4;
    const user = userEvent.setup();
    render(<ScreeningResultsPanel response={response} selectedRow={null} onSelect={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Not reviewed" })).toBeDisabled();
    expect(screen.getByText("Quiet ingredient")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Needs attention" }));
    expect(screen.queryByText("Quiet ingredient")).not.toBeInTheDocument();
    expect(screen.getByText("3 results")).toBeInTheDocument();
  });

  it("supports ingredient search and a clear empty state", async () => {
    const user = userEvent.setup();
    render(<ScreeningResultsPanel response={testResponse} selectedRow={null} onSelect={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Search ingredients"), "not present");
    expect(screen.getByText("No results match these filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(screen.getByText("Aminophylline")).toBeInTheDocument();
  });

  it("filters not-reviewed rows only when reviewer information is available", async () => {
    const user = userEvent.setup();
    render(
      <ScreeningResultsPanel
        response={testResponse}
        reviewDataState="available"
        reviewItems={[reviewItem(1, "reviewed"), reviewItem(2, "in_review"), reviewItem(3, null)]}
        selectedRow={null}
        onSelect={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Not reviewed" }));
    expect(screen.getByText("Mystery Extract")).toBeInTheDocument();
    expect(screen.queryByText("Aminophylline")).not.toBeInTheDocument();
    expect(screen.queryByText("Tosylchloramide sodium")).not.toBeInTheDocument();
  });

  it("reports the exact visible source-row order after filtering", async () => {
    const user = userEvent.setup();
    const onVisibleRowsChange = vi.fn();
    render(<ScreeningResultsPanel response={testResponse} selectedRow={null} onSelect={vi.fn()} onVisibleRowsChange={onVisibleRowsChange} />);

    await waitFor(() => expect(onVisibleRowsChange).toHaveBeenLastCalledWith([1, 2, 3]));
    await user.type(screen.getByPlaceholderText("Search ingredients"), "Tosylchloramide");
    await waitFor(() => expect(onVisibleRowsChange).toHaveBeenLastCalledWith([2]));
  });

  it("shows the persisted partial-assembly boundary above calculated findings", () => {
    const response = structuredClone(testResponse);
    response.formulation.assembly_scope = {
      completeness: "partial",
      issue_codes: ["incomplete_supplier_disclosure", "material_usage_missing"],
      action_required_codes: ["material_usage_missing"],
      coverage_limitation_codes: ["incomplete_supplier_disclosure"],
      unresolved_material_ids: ["material-1"],
      incomplete_disclosure_material_ids: ["material-1"],
      unresolved_association_ids: [],
      source_document_ids: ["document-1"],
      calculated_from_trade_materials: true,
    };

    render(<ScreeningResultsPanel response={response} selectedRow={null} onSelect={vi.fn()} />);

    expect(screen.getByText("Some inputs still need attention")).toBeInTheDocument();
    expect(screen.getByText(/prevent a complete product conclusion/)).toBeInTheDocument();
    expect(screen.getByText("View screening coverage")).toBeInTheDocument();
    expect(screen.getByText(/How much of a raw material is used/)).toBeInTheDocument();
    expect(screen.getByText(/supplier file may list only some ingredients/)).toBeInTheDocument();
  });

  it("presents partial supplier disclosure as coverage rather than a correction request", () => {
    const response = structuredClone(testResponse);
    response.formulation.assembly_scope = {
      completeness: "partial",
      issue_codes: ["incomplete_supplier_disclosure"],
      action_required_codes: [],
      coverage_limitation_codes: ["incomplete_supplier_disclosure"],
      unresolved_material_ids: [],
      incomplete_disclosure_material_ids: ["material-1"],
      unresolved_association_ids: [],
      source_document_ids: ["document-1"],
      calculated_from_trade_materials: true,
    };

    render(<ScreeningResultsPanel response={response} selectedRow={null} onSelect={vi.fn()} />);

    expect(screen.getByText("Screening reflects the supplier information provided")).toBeInTheDocument();
    expect(screen.getByText(/not a request to invent missing values/)).toBeInTheDocument();
  });

  it("shows the evaluated aggregate rather than its calculation formula", () => {
    const response = structuredClone(testResponse);
    response.ingredient_results = [baseResult(1, "CAPRYLIC/CAPRIC TRIGLYCERIDE")];
    response.ingredient_results[0].submitted_ingredient.concentration = {
      concentration_type: "exact",
      value: 0.6,
      lower_bound: null,
      upper_bound: null,
      lower_inclusive: null,
      upper_inclusive: null,
      unit: "percent",
      basis: null,
      preparation_stage: "finished_product",
      original_text: "(6%) x (10%) / 100",
    };

    render(<ScreeningResultsPanel response={response} selectedRow={null} onSelect={vi.fn()} />);

    expect(screen.getByText("0.60%")).toBeInTheDocument();
    expect(screen.queryByText("(6%) x (10%) / 100")).not.toBeInTheDocument();
    expect(screen.getByText("Evaluated finished-product concentration")).toBeInTheDocument();
  });

  it("shows one subtle source note for a direct and supplier aggregate", () => {
    const response = structuredClone(testResponse);
    response.ingredient_results = [baseResult(7, "2-Phenoxyethanol")];
    response.formulation.assembly_calculation_snapshot = {
      aggregates: [{
        display_name: "2-Phenoxyethanol",
        aggregate_quantity: { kind: "range", lower: 1.27, upper: 1.36, unit: "percent" },
        contributions: [
          { contribution_id: "direct", source_type: "direct_ingredient", governing_document_id: "primary:test-a" },
          { contribution_id: "supplier", source_type: "material_constituent", source_material_id: "aegismix", governing_document_id: "aegismix.pdf" },
        ],
      }],
    };

    render(<ScreeningResultsPanel response={response} selectedRow={null} onSelect={vi.fn()} />);

    expect(screen.getAllByText("2-Phenoxyethanol")).toHaveLength(1);
    expect(screen.getByText("Combined from 2 sources · Formulation + 1 supplier")).toBeInTheDocument();
  });
});

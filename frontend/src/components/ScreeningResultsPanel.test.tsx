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
});

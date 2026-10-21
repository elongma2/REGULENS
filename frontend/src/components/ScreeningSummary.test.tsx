import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { testResponse } from "../test/fixtures";
import type { ReviewItem } from "../types/review";
import { ScreeningSummary } from "./ScreeningSummary";

const reviewItem = (row: number, status: ReviewItem["review_status"]): ReviewItem => ({
  id: `review-${row}`,
  screening_run_id: "run-1",
  subject_type: "ingredient",
  subject_key: `row-${row}`,
  submitted_row_number: row,
  engine_finding: "identity_unresolved",
  requires_attention: true,
  review_status: status,
  updated_by: null,
  updated_at: "2026-10-20T08:00:00Z",
  reviewed_at: null,
});

function metric(label: string): HTMLElement {
  return screen.getByText(label).closest("div")!;
}

describe("ScreeningSummary", () => {
  it("counts attention from regulatory results and shows available reviewer metrics", () => {
    render(
      <ScreeningSummary
        summary={testResponse.summary}
        results={testResponse.ingredient_results}
        reviewItems={[reviewItem(1, "reviewed"), reviewItem(2, "in_review"), reviewItem(3, null)]}
        reviewDataState="available"
        openFindingFollowUps={2}
      />,
    );

    expect(within(metric("ingredients screened")).getByText("3")).toBeInTheDocument();
    expect(within(metric("ingredient results need attention")).getByText("3")).toBeInTheDocument();
    expect(within(metric("ingredient identities unresolved")).getByText("1")).toBeInTheDocument();
    expect(within(metric("reviews remaining")).getByText("2")).toBeInTheDocument();
    expect(within(metric("open finding follow-ups")).getByText("2")).toBeInTheDocument();
  });

  it("renders real zero values when reviewer information is available", () => {
    render(
      <ScreeningSummary
        summary={testResponse.summary}
        results={testResponse.ingredient_results}
        reviewItems={[]}
        reviewDataState="available"
        openFindingFollowUps={0}
      />,
    );

    expect(within(metric("reviews remaining")).getByText("0")).toBeInTheDocument();
    expect(within(metric("open finding follow-ups")).getByText("0")).toBeInTheDocument();
  });

  it("distinguishes unavailable and ad hoc reviewer information from zero", () => {
    const { rerender } = render(
      <ScreeningSummary
        summary={testResponse.summary}
        results={testResponse.ingredient_results}
        reviewItems={[]}
        reviewDataState="unavailable"
        openFindingFollowUps={0}
      />,
    );

    expect(screen.getByText("Reviewer workflow information unavailable")).toBeInTheDocument();
    expect(screen.queryByText("reviews remaining")).not.toBeInTheDocument();
    expect(screen.queryByText("open finding follow-ups")).not.toBeInTheDocument();

    rerender(
      <ScreeningSummary
        summary={testResponse.summary}
        results={testResponse.ingredient_results}
        reviewItems={[]}
        reviewDataState="not_applicable"
        openFindingFollowUps={0}
      />,
    );
    expect(screen.getByText("Reviewer workflow not saved in a case")).toBeInTheDocument();
    expect(screen.queryByText("reviews remaining")).not.toBeInTheDocument();
  });
});

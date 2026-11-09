import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FindingBadge } from "./FindingBadge";

describe("FindingBadge", () => {
  it("never presents a partially evaluated ingredient as a green scoped clearance", () => {
    render(<FindingBadge
      finding="no_issue_identified_within_scoped_rules"
      screeningDisposition="partially_evaluated"
    />);

    expect(screen.getByText("Partially evaluated")).toBeInTheDocument();
    expect(screen.queryByText("No issue identified within scoped rules")).not.toBeInTheDocument();
  });

  it("retains the bounded scoped result after every applicable check completed", () => {
    render(<FindingBadge
      finding="no_issue_identified_within_scoped_rules"
      screeningDisposition="fully_evaluated"
    />);

    expect(screen.getByText("No applicable restriction identified")).toBeInTheDocument();
  });
});

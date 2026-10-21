import { describe, expect, it } from "vitest";
import { nextCaseAction, resolveCaseAction, workflowFilter } from "./cases";
import type { CaseReviewSummary, CaseView, VersionStatus } from "../types/cases";

const summary = (changes: Partial<CaseReviewSummary> = {}): CaseReviewSummary => ({
  latest_screening_run_id: "run-1", latest_screening_formulation_version_id: "version-1",
  latest_screening_at: "2026-10-21T00:00:00Z", attention_results: 0,
  reviewer_items_remaining: 0, open_follow_ups: 0, unresolved_clarifications: 0,
  last_review_activity_at: null, ...changes,
});

function record(status?: VersionStatus): CaseView {
  const formulation = status ? {
    id: "version-1", case_id: "case-1", version_number: 1, original_filename: "formula.xlsx",
    status, revision: 1, created_at: "2026-10-20T00:00:00Z", updated_at: "2026-10-21T00:00:00Z", screening_count: status === "screened" ? 1 : 0,
  } : null;
  return {
    id: "case-1", organisation_id: "org-1", name: "Serum", client_name: null,
    product_type: null, status: "active", created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-21T00:00:00Z", archived_at: null,
    formulations: formulation ? [formulation] : [], latest_formulation: formulation,
  };
}

describe("case next action", () => {
  it("follows the persisted workflow precedence", () => {
    expect(nextCaseAction(record(), null)).toBe("Upload formulation");
    expect(nextCaseAction(record("failed"), null)).toBe("Retry interpretation");
    expect(nextCaseAction(record("interpreting"), null)).toBe("Continue clarification");
    expect(nextCaseAction(record("clarification_required"), null)).toBe("Continue clarification");
    expect(nextCaseAction(record("interpreted"), null)).toBe("Start screening");
    expect(nextCaseAction(record("ready_to_screen"), null)).toBe("Start screening");
    expect(nextCaseAction(record("screened"), summary({ reviewer_items_remaining: 2 }))).toBe("Continue review");
    expect(nextCaseAction(record("screened"), summary({ open_follow_ups: 1 }))).toBe("Continue review");
    expect(nextCaseAction(record("screened"), summary())).toBe("View screening");
    expect(nextCaseAction(record("screened"), null)).toBe("View screening");
  });

  it("builds context-preserving destinations", () => {
    expect(resolveCaseAction(record("interpreted"), summary({
      latest_screening_run_id: "old-run",
      latest_screening_formulation_version_id: "old-version",
      reviewer_items_remaining: 3,
    }))).toMatchObject({ kind: "screen", versionId: "version-1", href: "/cases/case-1/formulations/version-1?tab=formulation" });

    expect(resolveCaseAction(record("screened"), summary({ reviewer_items_remaining: 2 }))).toMatchObject({
      kind: "review",
      href: "/cases/case-1/formulations/version-1?tab=results&run=run-1&resume=review&drawer=review",
    });
    expect(resolveCaseAction(record("screened"), summary({ open_follow_ups: 1 }))).toMatchObject({
      kind: "review",
      href: "/cases/case-1/formulations/version-1?tab=activity&run=run-1&activity=open-followups",
    });
    expect(resolveCaseAction(record("screened"), null)).toMatchObject({
      kind: "view",
      href: "/cases/case-1/formulations/version-1?tab=results",
    });
    expect(workflowFilter(record("interpreted"))).toBe("ready");
  });
});

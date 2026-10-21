import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotesActivityPanel } from "./NotesActivityPanel";

const api = vi.hoisted(() => ({ getCaseActivity: vi.fn(), addReviewerNote: vi.fn(), updateFollowUp: vi.fn() }));
vi.mock("../api/review", () => api);

const context = {
  case_id: "case-1", case_name: "Serum", target_type: "finding" as const,
  target_label: "Finding · Row 4 · Retinol", formulation_version_id: "version-2",
  formulation_version_number: 2, screening_run_id: "run-3", screening_run_number: 3,
  screening_at: "2026-10-20T10:00:00Z", regulatory_dataset_id: "sg-2026-10",
  clarification_id: null, clarification_question_key: null, clarification_question: null,
  source_row_number: null, review_item_id: "review-4", submitted_row_number: 4,
  ingredient_name: "Retinol", engine_finding: "restriction_exceeded",
};

const activity = {
  case_id: "case-1",
  entries: [
    { id: "follow-1", kind: "follow_up" as const, occurred_at: "2026-10-21T10:00:00Z", author_name: "A. Reviewer", context, action_text: "Confirm concentration basis", details: null, status: "open" as const, created_at: "2026-10-21T09:00:00Z", updated_at: "2026-10-21T10:00:00Z", resolved_at: null, resolved_by_name: null },
    { id: "note-1", kind: "note" as const, occurred_at: "2026-10-20T11:00:00Z", author_name: "B. Reviewer", context: { ...context, target_type: "case" as const, target_label: "Case", formulation_version_id: null, formulation_version_number: null, screening_run_id: null, screening_run_number: null, screening_at: null, regulatory_dataset_id: null, review_item_id: null, submitted_row_number: null, ingredient_name: null, engine_finding: null }, body: "Client confirmed intended market." },
  ],
};

const savedCaseNote = {
  id: "note-2", case_id: "case-1", formulation_version_id: null, clarification_id: null,
  review_item_id: null, target_type: "case" as const, body: "Packaging decision confirmed.",
  created_by: "user-1", author_name: "A. Reviewer", created_at: "2026-10-21T11:00:00Z",
};

const resolvedFollowUp = {
  id: "follow-1", case_id: "case-1", formulation_version_id: "version-2", clarification_id: null,
  review_item_id: "review-4", target_type: "review_item" as const, target_label: "Finding · Row 4 · Retinol",
  action_text: "Confirm concentration basis", details: null, status: "resolved" as const,
  created_by: "user-1", author_name: "A. Reviewer", resolved_by: "user-1",
  created_at: "2026-10-21T09:00:00Z", updated_at: "2026-10-21T11:00:00Z", resolved_at: "2026-10-21T11:00:00Z",
};

describe("NotesActivityPanel", () => {
  beforeEach(() => {
    api.getCaseActivity.mockReset().mockResolvedValue(activity);
    api.addReviewerNote.mockReset().mockResolvedValue(savedCaseNote);
    api.updateFollowUp.mockReset().mockResolvedValue(resolvedFollowUp);
  });

  it("filters activity and updates an open follow-up centrally", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><NotesActivityPanel caseId="case-1" /></MemoryRouter>);
    expect((await screen.findAllByText(/Confirm concentration basis/)).length).toBeGreaterThan(0);
    const search = screen.getByPlaceholderText("Search notes, actions, context, or author");
    await user.type(search, "sg-2026-10");
    expect(screen.queryByText("Client confirmed intended market.")).not.toBeInTheDocument();
    await user.clear(search);
    await user.click(screen.getByRole("button", { name: "Notes" }));
    expect(screen.getByText("Client confirmed intended market.")).toBeInTheDocument();
    expect(screen.queryByText(/Confirm concentration basis/, { selector: ".activity-feed p" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All activity" }));
    await user.click(screen.getAllByRole("button", { name: "Resolve" })[0]);
    expect(api.updateFollowUp).toHaveBeenCalledWith("follow-1", { status: "resolved" });
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(api.getCaseActivity).toHaveBeenCalledTimes(1);
  });

  it("shows a saved case note immediately without reloading the feed", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><NotesActivityPanel caseId="case-1" /></MemoryRouter>);
    await screen.findAllByText(/Confirm concentration basis/);

    await user.click(screen.getByRole("button", { name: "Add case note" }));
    await user.type(screen.getByLabelText("Case note"), "Packaging decision confirmed.");
    await user.click(screen.getByRole("button", { name: "Save note" }));

    expect(await screen.findByText("Packaging decision confirmed.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Case note saved");
    expect(api.getCaseActivity).toHaveBeenCalledTimes(1);
  });

  it("keeps the case-note draft after a failed save", async () => {
    api.addReviewerNote.mockRejectedValueOnce(new Error("Save failed"));
    const user = userEvent.setup();
    render(<MemoryRouter><NotesActivityPanel caseId="case-1" /></MemoryRouter>);
    await screen.findAllByText(/Confirm concentration basis/);
    await user.click(screen.getByRole("button", { name: "Add case note" }));
    const editor = screen.getByLabelText("Case note");
    await user.type(editor, "Draft remains here");
    await user.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(editor).toHaveValue("Draft remains here");
  });

  it("renders long histories in batches without changing the searchable feed", async () => {
    api.getCaseActivity.mockResolvedValue({
      case_id: "case-1",
      entries: Array.from({ length: 55 }, (_, index) => ({
        id: `note-${index}`,
        kind: "note" as const,
        occurred_at: `2026-10-20T${String(23 - Math.floor(index / 3)).padStart(2, "0")}:${String((index % 3) * 10).padStart(2, "0")}:00Z`,
        author_name: "A. Reviewer",
        context: { ...context, target_type: "case" as const, target_label: "Case" },
        body: `Bulk note ${index}`,
      })),
    });
    const user = userEvent.setup();
    render(<MemoryRouter><NotesActivityPanel caseId="case-1" /></MemoryRouter>);

    expect(await screen.findByText("Bulk note 49")).toBeInTheDocument();
    expect(screen.queryByText("Bulk note 50")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Show older activity/ }));
    expect(screen.getByText("Bulk note 50")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search notes, actions, context, or author"), "Bulk note 54");
    expect(screen.getByText("Bulk note 54")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show older activity/ })).not.toBeInTheDocument();
  });
});

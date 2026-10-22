import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CasePage } from "./CasePage";

const api = vi.hoisted(() => ({ getCase: vi.fn(), deleteCase: vi.fn(), deleteFormulationVersion: vi.fn(), uploadCaseFormulation: vi.fn() }));
const reviewApi = vi.hoisted(() => ({ getReviewOverview: vi.fn(), getCaseActivity: vi.fn(), addReviewerNote: vi.fn() }));
vi.mock("../api/cases", () => api);
vi.mock("../api/review", () => reviewApi);

const savedCase = {
  id: "case-1", organisation_id: "org-1", name: "Facial Serum", client_name: "ABC Cosmetics",
  product_type: null, status: "active", created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z", archived_at: null,
  formulations: [
    { id: "version-2", case_id: "case-1", version_number: 2, original_filename: "v2.xlsx", status: "clarification_required", revision: 2, created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z", screening_count: 0 },
    { id: "version-1", case_id: "case-1", version_number: 1, original_filename: "v1.csv", status: "screened", revision: 4, created_at: "2026-10-12T00:00:00Z", updated_at: "2026-10-12T00:00:00Z", screening_count: 2 },
  ],
};

const savedCaseNote = {
  id: "note-2", case_id: "case-1", formulation_version_id: null, clarification_id: null,
  review_item_id: null, target_type: "case" as const, body: "Client approved the revised brief.",
  created_by: "user-1", author_name: "A. Reviewer", created_at: "2026-10-21T11:00:00Z",
};

describe("case detail", () => {
  beforeEach(() => {
    api.getCase.mockReset().mockResolvedValue(savedCase);
    api.deleteCase.mockReset().mockResolvedValue(undefined);
    api.deleteFormulationVersion.mockReset().mockResolvedValue(undefined);
    reviewApi.addReviewerNote.mockReset().mockResolvedValue(savedCaseNote);
    reviewApi.getCaseActivity.mockReset().mockResolvedValue({ case_id: "case-1", entries: [] });
    reviewApi.getReviewOverview.mockReset().mockResolvedValue({
      case_id: "case-1", current_formulation_version_id: "version-2", latest_screening_run_id: "run-1",
      latest_screening_formulation_version_id: "version-1",
      latest_screening_at: "2026-10-13T00:00:00Z", ingredients_screened: 24, attention_findings: 3,
      not_reviewed: 1, in_review: 1, awaiting_information: 1, reviewed: 0, open_follow_ups: 2,
      unresolved_clarifications: 1, note_count: 4, last_review_activity_at: "2026-10-13T01:00:00Z",
      recent_case_notes: [], open_follow_up_items: [],
    });
  });

  it("shows the newest version as current while retaining older versions", async () => {
    render(<MemoryRouter initialEntries={["/cases/case-1"]}><Routes><Route path="/cases/:caseId" element={<CasePage />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Facial Serum" })).toBeInTheDocument();
    expect(screen.getByText("Version 2")).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("Version 1")).toBeInTheDocument();
    expect(screen.getByText(/2 screening runs/)).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(screen.getByText("ingredient results need attention")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Continue clarification/ })).toHaveAttribute("href", "/cases/case-1/formulations/version-2?tab=formulation");
  });

  it("requires confirmation before deleting the complete case", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/cases/case-1"]}>
        <Routes><Route path="/cases/:caseId" element={<CasePage />} /><Route path="/cases" element={<h1>Cases list</h1>} /></Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByLabelText("More case actions"));
    await user.click(screen.getByRole("button", { name: "Delete case" }));
    const dialog = screen.getByRole("dialog", { name: /Delete “Facial Serum”/ });
    expect(dialog).toHaveTextContent("formulation versions");
    await user.click(within(dialog).getByRole("button", { name: "Delete case" }));
    expect(api.deleteCase).toHaveBeenCalledWith("case-1");
    expect(await screen.findByRole("heading", { name: "Cases list" })).toBeInTheDocument();
  });

  it("requires typed confirmation before deleting one formulation version", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/cases/case-1"]}><Routes><Route path="/cases/:caseId" element={<CasePage />} /></Routes></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Delete formulation version 2" }));
    const dialog = screen.getByRole("dialog", { name: /Delete formulation version 2/ });
    const action = within(dialog).getByRole("button", { name: "Delete formulation" });
    expect(action).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Type DELETE/i), "DELETE");
    await user.click(action);
    await waitFor(() => expect(api.deleteFormulationVersion).toHaveBeenCalledWith("version-2"));
    expect(screen.queryByText("Version 2")).not.toBeInTheDocument();
    expect(screen.getByText("Version 1")).toBeInTheDocument();
  });

  it("keeps a case-note draft when saving fails", async () => {
    reviewApi.addReviewerNote.mockRejectedValueOnce(new Error("Temporary failure"));
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/cases/case-1"]}><Routes><Route path="/cases/:caseId" element={<CasePage />} /></Routes></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Add case note" }));
    const editor = screen.getByLabelText("Case note");
    await user.type(editor, "Keep this professional observation");
    await user.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Temporary failure");
    expect(editor).toHaveValue("Keep this professional observation");
  });

  it("adds a saved case note to recent activity without refreshing the overview", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/cases/case-1"]}><Routes><Route path="/cases/:caseId" element={<CasePage />} /></Routes></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Add case note" }));
    await user.type(screen.getByLabelText("Case note"), "Client approved the revised brief.");
    await user.click(screen.getByRole("button", { name: "Save note" }));

    expect(await screen.findByText("Client approved the revised brief.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Case note saved");
    expect(reviewApi.getCaseActivity).toHaveBeenCalledTimes(1);
    expect(reviewApi.getReviewOverview).toHaveBeenCalledTimes(1);
  });
});

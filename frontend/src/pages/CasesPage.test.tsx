import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CasesPage } from "./CasesPage";

const api = vi.hoisted(() => ({ listCases: vi.fn(), createCase: vi.fn(), deleteCase: vi.fn() }));
vi.mock("../api/cases", () => api);

describe("case workspace", () => {
  beforeEach(() => {
    api.listCases.mockReset().mockResolvedValue([]);
    api.createCase.mockReset();
    api.deleteCase.mockReset().mockResolvedValue(undefined);
  });

  it("lists persisted case and version status", async () => {
    api.listCases.mockResolvedValue([{
      id: "case-1", organisation_id: "org-1", name: "Facial Serum", client_name: "ABC Cosmetics",
      product_type: null, status: "active", created_at: "2026-10-13T00:00:00Z",
      updated_at: "2026-10-13T00:00:00Z", archived_at: null, latest_finding_count: 2,
      review_summary: {
        latest_screening_run_id: null, latest_screening_formulation_version_id: null,
        latest_screening_at: null, attention_results: 0, reviewer_items_remaining: 0,
        open_follow_ups: 0, unresolved_clarifications: 1, last_review_activity_at: null,
      },
      formulations: [], latest_formulation: {
        id: "version-2", case_id: "case-1", version_number: 2, original_filename: "serum-v2.xlsx",
        status: "clarification_required", revision: 4, created_at: "2026-10-13T00:00:00Z",
        updated_at: "2026-10-13T00:00:00Z", screening_count: 0,
      },
    }]);
    render(<MemoryRouter initialEntries={["/cases"]}><CasesPage /></MemoryRouter>);
    expect((await screen.findAllByText("Facial Serum")).length).toBeGreaterThan(0);
    expect(screen.getByText("ABC Cosmetics")).toBeInTheDocument();
    expect(screen.getByText("Input clarification needed")).toBeInTheDocument();
    expect(screen.getByText("Version 2 · serum-v2.xlsx")).toBeInTheDocument();
    expect(screen.getAllByText("Continue clarification")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Continue where you left off/i })).toHaveAttribute("href", "/cases/case-1/formulations/version-2?tab=formulation");
  });

  it("deletes a case in place after accessible confirmation", async () => {
    api.listCases.mockResolvedValue([{
      id: "case-1", organisation_id: "org-1", name: "Delete Me", client_name: null,
      product_type: null, status: "active", created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z", archived_at: null,
      formulations: [], latest_formulation: null, review_summary: null,
    }]);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/cases"]}><CasesPage /></MemoryRouter>);
    await user.click(await screen.findByLabelText("More actions for Delete Me"));
    await user.click(screen.getByRole("button", { name: "Delete case" }));
    const dialog = screen.getByRole("dialog", { name: /Delete “Delete Me”/ });
    expect(dialog).toHaveTextContent("uploaded files");
    await user.click(within(dialog).getByRole("button", { name: "Delete case" }));
    expect(api.deleteCase).toHaveBeenCalledWith("case-1");
    expect(await screen.findByRole("status")).toHaveTextContent("was deleted");
    expect(screen.queryByText("Delete Me")).not.toBeInTheDocument();
  });

  it("keeps a failed deletion available and retries without reloading", async () => {
    api.listCases.mockResolvedValue([{
      id: "case-1", organisation_id: "org-1", name: "Keep Until Confirmed", client_name: null,
      product_type: null, status: "active", created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z", archived_at: null,
      formulations: [], latest_formulation: null, review_summary: null,
    }]);
    api.deleteCase.mockRejectedValueOnce(new Error("Uploaded files could not be removed")).mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/cases"]}><CasesPage /></MemoryRouter>);
    await user.click(await screen.findByLabelText("More actions for Keep Until Confirmed"));
    await user.click(screen.getByRole("button", { name: "Delete case" }));
    const dialog = screen.getByRole("dialog", { name: /Delete “Keep Until Confirmed”/ });
    await user.click(within(dialog).getByRole("button", { name: "Delete case" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Uploaded files could not be removed");
    expect(screen.getAllByText("Keep Until Confirmed").length).toBeGreaterThan(0);
    await user.click(within(dialog).getByRole("button", { name: "Retry deletion" }));

    expect(api.deleteCase).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("status")).toHaveTextContent("was deleted");
    expect(screen.queryByText("Keep Until Confirmed")).not.toBeInTheDocument();
  });

  it("searches and filters the compact case directory", async () => {
    api.listCases.mockResolvedValue([
      {
        id: "case-1", organisation_id: "org-1", name: "Facial Serum", client_name: "ABC Cosmetics",
        product_type: null, status: "active", created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z", archived_at: null,
        formulations: [], latest_formulation: { id: "version-1", case_id: "case-1", version_number: 1, original_filename: "serum.xlsx", status: "screened", revision: 4, created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z", screening_count: 1 },
        review_summary: { latest_screening_run_id: "run-1", latest_screening_formulation_version_id: "version-1", latest_screening_at: "2026-10-13T00:00:00Z", attention_results: 1, reviewer_items_remaining: 1, open_follow_ups: 0, unresolved_clarifications: 0, last_review_activity_at: null },
      },
      {
        id: "case-2", organisation_id: "org-1", name: "Body Lotion", client_name: "XYZ",
        product_type: null, status: "archived", created_at: "2026-10-12T00:00:00Z", updated_at: "2026-10-12T00:00:00Z", archived_at: "2026-10-12T00:00:00Z",
        formulations: [], latest_formulation: null, review_summary: null,
      },
    ]);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/cases"]}><CasesPage /></MemoryRouter>);
    await screen.findAllByText("Facial Serum");
    await user.type(screen.getByPlaceholderText("Search case, client, or file"), "XYZ");
    expect(screen.getByText("No cases match these filters")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Lifecycle"), "all");
    expect(screen.getByText("Body Lotion")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Review"), "unavailable");
    expect(screen.getByText("Review information unavailable")).toBeInTheDocument();
  });

  it("creates a case from the dedicated route", async () => {
    api.createCase.mockResolvedValue({ id: "case-new" });
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/cases/new"]}>
        <Routes>
          <Route path="/cases/new" element={<CasesPage />} />
          <Route path="/cases/:caseId" element={<h1>Created case</h1>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText("Case / product name"), "Facial Serum");
    await user.type(screen.getByLabelText(/Client name/), "ABC Cosmetics");
    await user.click(screen.getByRole("button", { name: "Create case" }));
    expect(api.createCase).toHaveBeenCalledWith("Facial Serum", "ABC Cosmetics");
    expect(await screen.findByRole("heading", { name: "Created case" })).toBeInTheDocument();
  });
});

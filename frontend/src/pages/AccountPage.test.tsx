import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccountPage } from "./AccountPage";

const deleteAccount = vi.fn(); const clearLocalSession = vi.fn();
vi.mock("../api/cases", () => ({
  getMe: vi.fn(async () => ({ id: "user-1", email: "pilot@example.test", display_name: "Pilot", default_organisation_id: "org-1", organisations: [{ id: "org-1", name: "Pilot's Workspace", role: "owner", created_at: "2026-10-22T00:00:00Z" }] })),
  deleteAccount: () => deleteAccount(),
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { email: "pilot@example.test" }, signOut: vi.fn(), clearLocalSession }) }));

describe("AccountPage", () => {
  beforeEach(() => { deleteAccount.mockReset(); clearLocalSession.mockReset(); deleteAccount.mockResolvedValue(undefined); clearLocalSession.mockResolvedValue(undefined); });
  it("deletes only after typed confirmation, clears the local session, and redirects", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/account"]}><Routes><Route path="/account" element={<AccountPage />} /><Route path="/sign-in" element={<div>Signed out account deleted</div>} /></Routes></MemoryRouter>);
    expect(await screen.findByText("Pilot's Workspace")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete account" }));
    const confirmation = screen.getByLabelText(/Type DELETE/i);
    const action = screen.getAllByRole("button", { name: "Delete account" }).at(-1)!;
    expect(action).toBeDisabled();
    await user.type(confirmation, "DELETE");
    await user.click(action);
    await waitFor(() => expect(deleteAccount).toHaveBeenCalledOnce());
    expect(clearLocalSession).toHaveBeenCalledOnce();
    expect(await screen.findByText("Signed out account deleted")).toBeInTheDocument();
  });
});

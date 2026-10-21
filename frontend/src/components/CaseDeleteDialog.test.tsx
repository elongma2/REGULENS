import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CaseDeleteDialog } from "./CaseDeleteDialog";

function Harness({ onConfirm = vi.fn() }: { onConfirm?: () => void }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" onClick={() => setOpen(true)}>Open deletion</button>
    <CaseDeleteDialog caseName={open ? "Facial Serum" : null} busy={false} error={null} onCancel={() => setOpen(false)} onConfirm={onConfirm} />
  </>;
}

describe("CaseDeleteDialog", () => {
  it("focuses Cancel, closes with Escape, and restores the opener", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open deletion" });
    await user.click(opener);
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus());
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("disables all dismissal and confirmation controls while deleting", () => {
    render(<CaseDeleteDialog caseName="Facial Serum" busy error={null} onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deleting…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close delete confirmation" })).toBeDisabled();
  });
});

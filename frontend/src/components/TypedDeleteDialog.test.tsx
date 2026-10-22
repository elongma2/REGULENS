import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TypedDeleteDialog } from "./TypedDeleteDialog";

describe("TypedDeleteDialog", () => {
  it("requires the exact DELETE confirmation and supports Escape", async () => {
    const user = userEvent.setup(); const confirm = vi.fn(); const cancel = vi.fn();
    render(<TypedDeleteDialog open title="Delete formulation?" description="Permanent." actionLabel="Delete formulation" busy={false} error={null} onCancel={cancel} onConfirm={confirm} />);
    const action = screen.getByRole("button", { name: "Delete formulation" });
    expect(action).toBeDisabled();
    await user.type(screen.getByLabelText(/Type DELETE/i), "delete");
    expect(action).toBeDisabled();
    await user.clear(screen.getByLabelText(/Type DELETE/i));
    await user.type(screen.getByLabelText(/Type DELETE/i), "DELETE");
    expect(action).toBeEnabled();
    await user.click(action);
    expect(confirm).toHaveBeenCalledOnce();
    await user.keyboard("{Escape}");
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("retains a deletion error for retry", () => {
    render(<TypedDeleteDialog open title="Delete account?" description="Permanent." actionLabel="Delete account" busy={false} error="Storage unavailable" onCancel={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Storage unavailable");
  });
});

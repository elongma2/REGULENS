import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProductContextCombobox } from "./ProductContextCombobox";

const contexts = [
  "(a) Skin products (i) For general use (ii) For professional use",
  "Artificial nail systems",
  "Rinse-off hair products",
  "Toothpaste",
];

describe("ProductContextCombobox", () => {
  it("shows the complete accepted list and selects a long context", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    const completeList = [
      ...contexts,
      ...Array.from({ length: 102 }, (_, index) => `Accepted product context ${index + 1}`),
    ];
    render(<ProductContextCombobox value="" options={completeList} unresolved disabled={false} onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { name: "Agent Product context" }));

    expect(screen.getByText("106 accepted contexts")).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(107);
    await user.click(screen.getByRole("option", { name: contexts[0] }));
    expect(onSelect).toHaveBeenCalledWith(contexts[0]);
  });

  it("filters options and supports keyboard selection", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<ProductContextCombobox value="" options={contexts} unresolved disabled={false} onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { name: "Agent Product context" }));
    const search = screen.getByRole("combobox", { name: "Search accepted product contexts" });
    await user.type(search, "tooth");
    expect(screen.getByText("1 of 4 contexts")).toBeInTheDocument();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onSelect).toHaveBeenCalledWith("Toothpaste");
  });

  it("closes on Escape and does not open while disabled", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ProductContextCombobox value="Toothpaste" options={contexts} unresolved={false} disabled={false} onSelect={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Agent Product context" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    rerender(<ProductContextCombobox value="Toothpaste" options={contexts} unresolved={false} disabled onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Agent Product context" })).toBeDisabled();
  });
});

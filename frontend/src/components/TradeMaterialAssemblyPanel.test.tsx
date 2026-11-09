import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TradeMaterialAssemblyPanel } from "./TradeMaterialAssemblyPanel";

const api = vi.hoisted(() => ({
  getOrInitializeFormulationAssembly: vi.fn(),
  refreshFormulationAssembly: vi.fn(),
  updateFormulationAssembly: vi.fn(),
}));
vi.mock("../api/cases", () => api);

const document = {
  id: "doc-1", formulation_version_id: "version-1", supplier_document_id: "supplier-1",
  original_filename: "OPTASENSE.pdf", mime_type: "application/pdf", sha256: "a".repeat(64),
  page_count: 1, processing_status: "ready", detected_roles: [],
  confirmed_roles: ["supplier_composition"], parsed_content: {}, extraction_result: { supplier_materials: [{}] },
  processing_diagnostics: {}, error: null, document_revision_label: "Rev 1",
  governing_for_material: true, attached_extraction_key: "key", revision: 1,
  created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:00Z",
} as const;

const quantity = {
  kind: "range", value: null, lower: 25, upper: 50,
  lower_inclusive: true, upper_inclusive: true, unit: "percent", basis: null,
  preparation_stage: null, quantity_scope: "supplier_material", raw_text: "C",
  reported_code: "C", legend_entry_id: "legend:C", approximate: false,
} as const;

const preparation = {
  assembly_revision: 1,
  state: {
    direct_ingredients: [], source_document_ids: ["doc-1"],
    source_document_snapshots: { "doc-1": "assembly-v3|key|revision:1|governing:true|roles:supplier_composition" },
    formulation_name: "Pilot",
    product_context: null, product_applicability: {},
    materials: [{
      material_id: "material-1", trade_name: "OPTASENSE", supplier_name: "Supplier",
      product_code: "EN80159", finished_product_usage: null,
      attached_document_ids: ["doc-1"], governing_document_id: "doc-1",
      disclosure_status: "complete", confirmation_status: "confirmed",
      constituents: [{
        constituent_id: "glycerin", submitted_name: "GLYCERIN", cas_number: "56-81-5",
        composition_quantity: quantity, verified_identity_group: "catalogue:glycerin",
        source_evidence: [{
          document_id: "doc-1", page: 2, source_row: 6, source_column: null,
          source_snippet: "GLYCERIN 56-81-5 C", raw_value: "GLYCERIN 56-81-5 C",
        }],
        regulated_functions: [], role_label: null, user_edits: {},
      }],
    }],
  },
  assembly: {
    assembly_revision: 1, completeness: "partial", included_ingredients: [],
    unresolved_raw_materials: [], incomplete_disclosures: ["material-1"],
    unresolved_associations: [], excluded_items: [], evaluated_scope: {}, calculation_snapshot: {},
    issues: [{
      issue_id: "usage", code: "material_usage_missing", severity: "review_required",
      message: "Finished-product usage is missing for OPTASENSE.",
      reviewer_action: "Enter how much of this trade material is used in the finished product.",
      blocking_for_calculation: true, blocking_for_full_evaluation: true,
      document_ids: ["doc-1"], material_ids: ["material-1"], constituent_ids: [],
    }],
  },
  formulation: null,
};

describe("TradeMaterialAssemblyPanel", () => {
  beforeEach(() => {
    api.getOrInitializeFormulationAssembly.mockReset().mockResolvedValue(preparation);
    api.refreshFormulationAssembly.mockReset().mockResolvedValue(preparation);
    api.updateFormulationAssembly.mockReset().mockImplementation(async (_id, revision, state) => ({
      ...preparation, assembly_revision: revision + 1, state,
      assembly: { ...preparation.assembly, completeness: "complete", issues: [], included_ingredients: [{
        verified_identity_group: "catalogue:glycerin", display_name: "GLYCERIN",
        cas_number: "56-81-5", aggregate_quantity: quantity, contributions: [], completeness: "complete",
      }] },
    }));
  });

  it("shows the source-backed material and resolved document legend", async () => {
    render(<TradeMaterialAssemblyPanel versionId="version-1" documents={[document as never]} />);

    expect(await screen.findByRole("heading", { name: "OPTASENSE" })).toBeInTheDocument();
    await userEvent.click(screen.getByText("View extracted ingredients"));
    expect(screen.getByDisplayValue("GLYCERIN")).toBeInTheDocument();
    expect(screen.getByDisplayValue("25–50%")).toBeInTheDocument();
    expect(screen.getByText("Matched")).toBeInTheDocument();
    expect(screen.getByText(/Page 2 · GLYCERIN 56-81-5 C/)).toBeInTheDocument();
  });

  it("reports recognised trade names to the formulation review", async () => {
    const onHandledMaterialNamesChange = vi.fn();
    render(<TradeMaterialAssemblyPanel compact versionId="version-1" documents={[document as never]} onHandledMaterialNamesChange={onHandledMaterialNamesChange} />);

    await waitFor(() => expect(onHandledMaterialNamesChange).toHaveBeenCalledWith(["OPTASENSE", "EN80159"]));
  });

  it("shows one compact attention queue and opens a focused material editor", async () => {
    const user = userEvent.setup();
    render(<TradeMaterialAssemblyPanel compact versionId="version-1" documents={[document as never]} />);

    expect(await screen.findByRole("heading", { name: "Needs attention" })).toBeInTheDocument();
    expect(screen.getByText("1 check remaining")).toBeInTheDocument();
    expect(screen.queryByText("Ingredient calculation")).not.toBeInTheDocument();
    expect(screen.getByText("Finished-product usage is missing for OPTASENSE.")).toBeInTheDocument();
    expect(screen.getAllByText("Enter how much of this trade material is used in the finished product.").length).toBeGreaterThan(0);
    expect(screen.getByText(/calculate the finished-product ingredient concentrations and screen them in one step/)).toBeInTheDocument();
    expect(screen.getByText("Needs input")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /OPTASENSE/ }));
    expect(screen.getByRole("dialog", { name: "Edit OPTASENSE" })).toBeInTheDocument();
    expect(screen.getByText("Must be fixed before this material can be calculated.")).toBeInTheDocument();
    expect(screen.getByLabelText("Used in finished product")).toBeInTheDocument();
  });

  it("revalidates compact edits automatically before screening", async () => {
    const user = userEvent.setup();
    render(<TradeMaterialAssemblyPanel compact versionId="version-1" documents={[document as never]} />);

    await user.click(await screen.findByRole("button", { name: /OPTASENSE/ }));
    await user.type(screen.getByLabelText("Used in finished product"), "2");
    await user.tab();

    await waitFor(() => expect(api.updateFormulationAssembly).toHaveBeenCalledTimes(1), { timeout: 2_000 });
    expect(await screen.findByText("All corrections are up to date.")).toBeInTheDocument();
  });

  it("keeps partial supplier disclosure in coverage instead of the attention queue", async () => {
    const coverageOnly = {
      ...preparation,
      state: {
        ...preparation.state,
        materials: preparation.state.materials.map((item) => ({
          ...item,
          disclosure_status: "partial",
          finished_product_usage: {
            ...quantity,
            kind: "exact",
            value: 2,
            lower: null,
            upper: null,
            raw_text: "2%",
            quantity_scope: "finished_product",
            preparation_stage: "finished_product",
          },
        })),
      },
      assembly: {
        ...preparation.assembly,
        issues: [{
          issue_id: "coverage",
          code: "incomplete_supplier_disclosure",
          severity: "warning",
          message: "Supplier disclosure is partial.",
          reviewer_action: "Screen the disclosed ingredients and retain the limitation.",
          blocking_for_calculation: false,
          blocking_for_full_evaluation: true,
          document_ids: ["doc-1"],
          material_ids: ["material-1"],
          constituent_ids: [],
        }],
      },
    };
    api.getOrInitializeFormulationAssembly.mockResolvedValue(coverageOnly);

    render(<TradeMaterialAssemblyPanel compact versionId="version-1" documents={[document as never]} />);

    expect(await screen.findByRole("heading", { name: "Screening coverage" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Needs attention" })).not.toBeInTheDocument();
    expect(screen.getByText(/without asking you to invent the rest/)).toBeInTheDocument();
  });

  it("shows a cross-document impossible total as a clear correction instead of hiding it", async () => {
    const impossibleTotal = {
      ...preparation,
      assembly: {
        ...preparation.assembly,
        completeness: "blocked",
        issues: [{
          issue_id: "impossible-total",
          code: "impossible_composition_total",
          severity: "error",
          message: "The combined finished-product amount for GLYCERIN is outside the possible 0% to 100% range.",
          reviewer_action: "Check whether more than one finished formulation or duplicate source was uploaded, then correct the affected amount or document association.",
          blocking_for_calculation: false,
          blocking_for_full_evaluation: true,
          document_ids: ["doc-1", "doc-2"],
          material_ids: [],
          constituent_ids: ["glycerin"],
        }],
      },
    };
    api.getOrInitializeFormulationAssembly.mockResolvedValue(impossibleTotal);

    render(<TradeMaterialAssemblyPanel compact versionId="version-1" documents={[document as never]} />);

    expect(await screen.findByText(/combined finished-product amount for GLYCERIN/)).toBeInTheDocument();
    expect(screen.getByText(/more than one finished formulation or duplicate source/)).toBeInTheDocument();
    expect(screen.getByText("Can screen with limits")).toBeInTheDocument();
    expect(screen.queryByText(/No changes needed/)).not.toBeInTheDocument();
  });

  it("keeps hook order stable when documents arrive after the case opens", async () => {
    const { rerender } = render(<TradeMaterialAssemblyPanel compact versionId="version-1" documents={[]} />);
    expect(screen.queryByRole("heading", { name: "Formulation overview" })).not.toBeInTheDocument();

    rerender(<TradeMaterialAssemblyPanel compact versionId="version-1" documents={[document as never]} />);

    expect(await screen.findByRole("heading", { name: "Formulation overview" })).toBeInTheDocument();
    expect(screen.getAllByText("OPTASENSE").length).toBeGreaterThan(0);
  });

  it("refreshes assembly once when a saved document extraction snapshot changes", async () => {
    const reprocessed = { ...document, attached_extraction_key: "key-v2", revision: 2 };
    const refreshed = {
      ...preparation,
      assembly_revision: 2,
      state: {
        ...preparation.state,
        source_document_snapshots: {
          "doc-1": "assembly-v3|key-v2|revision:2|governing:true|roles:supplier_composition",
        },
      },
    };
    api.refreshFormulationAssembly.mockResolvedValue(refreshed);

    render(<TradeMaterialAssemblyPanel versionId="version-1" documents={[reprocessed as never]} />);

    await waitFor(() => expect(api.refreshFormulationAssembly).toHaveBeenCalledWith("version-1"));
    expect(await screen.findByRole("heading", { name: "OPTASENSE" })).toBeInTheDocument();
  });

  it("saves formulation-specific usage separately from supplier composition", async () => {
    const user = userEvent.setup();
    render(<TradeMaterialAssemblyPanel versionId="version-1" documents={[document as never]} />);
    const input = await screen.findByLabelText("Used in finished product");
    await user.type(input, "2");
    await user.tab();
    await user.click(screen.getByRole("button", { name: "Save and recalculate" }));

    await waitFor(() => expect(api.updateFormulationAssembly).toHaveBeenCalled());
    const [, revision, state] = api.updateFormulationAssembly.mock.calls[0];
    expect(revision).toBe(1);
    expect(state.materials[0].finished_product_usage.value).toBe(2);
    expect(state.materials[0].finished_product_usage.quantity_scope).toBe("finished_product");
    expect(state.materials[0].disclosure_status).toBe("complete");
    expect(await screen.findByText("Calculated")).toBeInTheDocument();
  });

  it("preserves ranged material usage and reviewer-confirmed regulated functions", async () => {
    const user = userEvent.setup();
    render(<TradeMaterialAssemblyPanel versionId="version-1" documents={[document as never]} />);
    const input = await screen.findByLabelText("Used in finished product");
    await user.type(input, "1-2%");
    await user.tab();
    await user.click(screen.getByText("View extracted ingredients"));
    await user.click(screen.getByRole("checkbox", { name: "Preservative" }));
    await user.click(screen.getByRole("button", { name: "Save and recalculate" }));

    await waitFor(() => expect(api.updateFormulationAssembly).toHaveBeenCalled());
    const material = api.updateFormulationAssembly.mock.calls[0][2].materials[0];
    expect(material.finished_product_usage).toMatchObject({
      kind: "range", lower: 1, upper: 2,
      quantity_scope: "finished_product", preparation_stage: "finished_product",
    });
    expect(material.constituents[0].regulated_functions).toEqual(["preservative"]);
  });

  it("persists reviewer corrections to a constituent before recalculation", async () => {
    const user = userEvent.setup();
    render(<TradeMaterialAssemblyPanel versionId="version-1" documents={[document as never]} />);
    await screen.findByRole("heading", { name: "OPTASENSE" });
    await user.click(screen.getByText("View extracted ingredients"));

    const name = screen.getByLabelText("Ingredient name");
    await user.clear(name);
    await user.type(name, "GLYCERIN USP");
    await user.tab();
    const quantityInput = screen.getByLabelText("Inside raw material");
    await user.clear(quantityInput);
    await user.type(quantityInput, "30-45%");
    await user.tab();
    await user.click(screen.getByRole("button", { name: "Save and recalculate" }));

    await waitFor(() => expect(api.updateFormulationAssembly).toHaveBeenCalled());
    const state = api.updateFormulationAssembly.mock.calls[0][2];
    expect(state.materials[0].constituents[0].submitted_name).toBe("GLYCERIN USP");
    expect(state.materials[0].constituents[0].composition_quantity).toMatchObject({
      kind: "range", lower: 30, upper: 45, unit: "percent",
      quantity_scope: "supplier_material",
    });
    expect(state.materials[0].constituents[0].user_edits.submitted_name).toBe("GLYCERIN USP");
  });

  it("allows missing supplier constituents to be added and incorrect rows removed", async () => {
    const user = userEvent.setup();
    render(<TradeMaterialAssemblyPanel versionId="version-1" documents={[document as never]} />);
    await screen.findByRole("heading", { name: "OPTASENSE" });
    await user.click(screen.getByText("View extracted ingredients"));

    await user.click(screen.getByRole("button", { name: "Add missing ingredient" }));
    expect(screen.getByDisplayValue("New ingredient")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove GLYCERIN" }));
    await user.click(screen.getByRole("button", { name: "Save and recalculate" }));

    await waitFor(() => expect(api.updateFormulationAssembly).toHaveBeenCalled());
    const state = api.updateFormulationAssembly.mock.calls[0][2];
    expect(state.materials[0].constituents).toHaveLength(1);
    expect(state.materials[0].constituents[0].user_edits.added_by_reviewer).toBe(true);
    expect(state.materials[0].removed_constituent_ids).toContain("glycerin");
  });

  it("allows a reviewer to correct the formulation-local material association", async () => {
    const user = userEvent.setup();
    render(<TradeMaterialAssemblyPanel versionId="version-1" documents={[document as never]} />);
    await screen.findByRole("heading", { name: "OPTASENSE" });
    await user.click(screen.getByText("Supplier details"));

    await user.clear(screen.getByLabelText("Trade name"));
    await user.type(screen.getByLabelText("Trade name"), "OPTASENSE RMA");
    await user.clear(screen.getByLabelText("Supplier"));
    await user.type(screen.getByLabelText("Supplier"), "Croda");
    await user.clear(screen.getByLabelText("Product or material code"));
    await user.type(screen.getByLabelText("Product or material code"), "EN80159");
    await user.click(screen.getByRole("button", { name: "Save and recalculate" }));

    await waitFor(() => expect(api.updateFormulationAssembly).toHaveBeenCalled());
    const material = api.updateFormulationAssembly.mock.calls[0][2].materials[0];
    expect(material).toMatchObject({
      trade_name: "OPTASENSE RMA",
      supplier_name: "Croda",
      product_code: "EN80159",
      confirmation_status: "confirmed",
    });
  });
});

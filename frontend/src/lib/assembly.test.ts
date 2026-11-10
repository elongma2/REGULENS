import { describe, expect, it } from "vitest";
import { baseResult } from "../test/fixtures";
import { combinedSourceNote, findAssemblyAggregate, formatEvaluatedAssemblyQuantity } from "./assembly";

describe("assembly result matching", () => {
  it("uses concentration to distinguish legacy split aggregates with the same CAS", () => {
    const result = baseResult(8, "2-Phenoxyethanol");
    result.submitted_ingredient.cas_number = "122-99-6";
    result.submitted_ingredient.concentration = {
      concentration_type: "range",
      lower_bound: 0.27,
      upper_bound: 0.36,
      lower_inclusive: true,
      upper_inclusive: true,
      value: null,
      unit: "percent",
      basis: null,
      preparation_stage: "finished_product",
      original_text: null,
    };
    const snapshot = {
      aggregates: [{
        verified_identity_group: "catalogue:phenoxyethanol",
        display_name: "PHENOXYETHANOL",
        cas_number: "122-99-6",
        aggregate_quantity: { kind: "exact", value: 1, unit: "percent" },
        contributions: [
          { source_type: "direct_ingredient" },
          { source_type: "material_constituent", source_material_id: "aegis" },
          { source_type: "material_constituent", source_material_id: "cava" },
        ],
      }, {
        verified_identity_group: "singapore:phenoxyethanol",
        display_name: "2-PHENOXYETHANOL",
        cas_number: "122-99-6",
        aggregate_quantity: { kind: "range", lower: 0.27, upper: 0.36, unit: "percent" },
        contributions: [{ source_type: "material_constituent", source_material_id: "bexa" }],
      }],
    };

    expect(findAssemblyAggregate(snapshot, result)?.verified_identity_group).toBe("singapore:phenoxyethanol");
    expect(combinedSourceNote(snapshot, result)).toBeNull();
  });

  it("shows one four-source aggregate after verified identities are combined", () => {
    const result = baseResult(7, "2-Phenoxyethanol");
    result.submitted_ingredient.cas_number = "122-99-6";
    result.submitted_ingredient.concentration = {
      concentration_type: "range",
      lower_bound: 1.27,
      upper_bound: 1.36,
      lower_inclusive: true,
      upper_inclusive: true,
      value: null,
      unit: "percent",
      basis: null,
      preparation_stage: "finished_product",
      original_text: null,
    };
    const snapshot = {
      aggregates: [{
        verified_identity_group: "catalogue:phenoxyethanol",
        display_name: "PHENOXYETHANOL",
        cas_number: "122-99-6",
        aggregate_quantity: { kind: "range", lower: 1.27, upper: 1.36, unit: "percent" },
        contributions: [
          { source_type: "direct_ingredient" },
          { source_type: "material_constituent", source_material_id: "aegis" },
          { source_type: "material_constituent", source_material_id: "bexa" },
          { source_type: "material_constituent", source_material_id: "cava" },
        ],
      }],
    };

    expect(combinedSourceNote(snapshot, result)).toBe("Combined from 4 sources · Formulation + 3 suppliers");
  });

  it("keeps q.s. visible beside the known supplier contribution", () => {
    expect(formatEvaluatedAssemblyQuantity({
      display_name: "AQUA",
      aggregate_quantity: { kind: "lower_bound", lower: 0.45, unit: "percent" },
      contributions: [{
        source_type: "direct_ingredient",
        finished_product_quantity: {
          kind: "unknown", unit: "percent", raw_text: "q.s. to 100%",
        },
      }, {
        source_type: "material_constituent",
        source_material_id: "boundshift",
        finished_product_quantity: { kind: "exact", value: 0.45, unit: "percent" },
      }],
    })).toBe("q.s. to 100% · known supplier contribution 0.45%");
  });
});

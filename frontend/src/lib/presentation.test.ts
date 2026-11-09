import { describe, expect, it } from "vitest";
import { baseResult } from "../test/fixtures";
import {
  comparisonRows,
  displayIngredientName,
  reviewReasonLabel,
} from "./presentation";

describe("evidence presentation", () => {
  it("shortens only the literal source-backed except delimiter", () => {
    const result = baseResult(1, "Exact submitted conditional wording");
    result.identity.resolved_singapore_substance_id = "sg-diethylene";
    result.identity.singapore_candidates = [{
      substance_id: "sg-diethylene",
      source_document: "singapore_regulations_2025_12_01",
      regulatory_section: "Third Schedule Part I",
      reference_number: "A1140",
      original_substance_name: "Diethylene glycol (except if it is present as an unavoidable trace amount)",
      normalized_substance_name: "diethylene glycol (except if it is present as an unavoidable trace amount)",
      cas_numbers: [], match_methods: ["exact_name"], cross_reference_statuses: [],
    }];
    expect(displayIngredientName(result)).toBe("Diethylene glycol");
    expect(result.submitted_ingredient.name).toBe("Exact submitted conditional wording");
    expect(result.identity.singapore_candidates[0].original_substance_name).toContain("(except if");
  });

  it("does not strip legitimate chemical parentheses", () => {
    const result = baseResult(1, "Chemical");
    result.identity.resolved_singapore_substance_id = "sg-chemical";
    result.identity.singapore_candidates = [{
      substance_id: "sg-chemical", source_document: "sg", regulatory_section: "Third Schedule Part II",
      reference_number: "1", original_substance_name: "Chemical (INN) (2-hydroxyethyl)",
      normalized_substance_name: "chemical (inn) (2-hydroxyethyl)", cas_numbers: [],
      match_methods: ["exact_name"], cross_reference_statuses: [],
    }];
    expect(displayIngredientName(result)).toBe("Chemical (INN) (2-hydroxyethyl)");
  });

  it("formats ACD fields without mutating their raw representation", () => {
    const raw = {
      cross_reference_id: "xref", regulatory_mapping: "mapping", reference_number: "5",
      acd_rule_ids: [], singapore_rule_ids: [], match_basis: "reference_number", comparison_status: "changed" as const,
      field_differences: {
        product_context: { acd: "[parent] ", singapore: "[parent] All products" },
        concentration: {
          acd: '[parent] {"basis":null,"comparator":"less_than_or_equal","preparation_stage":"ready_for_use","source_text":"0.2%","unit":"percent","value":0.2}',
          singapore: '[parent] {"basis":null,"comparator":"less_than_or_equal","preparation_stage":"finished_product","source_text":"0.2%","unit":"percent","value":0.2}',
        },
      },
      candidate_matches: [], professional_review_required: true, review_reasons: [],
    };
    const before = structuredClone(raw.field_differences);
    const rows = comparisonRows(raw);
    expect(rows).toContainEqual({ field: "Product context", acd: "—", singapore: "All products" });
    expect(rows).toContainEqual({ field: "Preparation stage", acd: "Ready for use", singapore: "Finished product" });
    expect(raw.field_differences).toEqual(before);
  });

  it("shows only validated requirement differences when semantic comparison is available", () => {
    const reference = {
      cross_reference_id: "xref", regulatory_mapping: "mapping", reference_number: "29",
      acd_rule_ids: ["acd"], singapore_rule_ids: ["sg"], match_basis: "reference_number",
      comparison_status: "changed" as const,
      field_differences: { substance_name: { acd: "2 Phenoxyethanol", singapore: "2-Phenoxyethanol" } },
      candidate_matches: [], professional_review_required: false, review_reasons: [],
      semantic_comparison_status: "material_difference" as const,
      requirement_differences: [{ aspect: "concentration_limit", acd: "0.8%", singapore: "1%", effect: "Different maximum" }],
    };

    expect(comparisonRows(reference)).toEqual([{ field: "Concentration limit", acd: "0.8%", singapore: "1%" }]);
  });

  it("maps internal review codes to bounded readable labels", () => {
    expect(reviewReasonLabel("no_source_backed_identity_match")).toMatch(/could not match this ingredient/);
    expect(reviewReasonLabel("sg-rule: ambiguous_multi_case_concentration_not_normalized")).toBe(
      "This rule has several limits. Confirm which one applies to this product.",
    );
    expect(reviewReasonLabel("sg-rule: incompatible preparation_stage; no conversion performed")).toBe(
      "The percentage is for a different preparation stage. Check when this concentration applies.",
    );
    expect(reviewReasonLabel("conditional_prohibition_wording_not_structured")).toBe(
      "This rule has an exception that still needs checking.",
    );
  });
});

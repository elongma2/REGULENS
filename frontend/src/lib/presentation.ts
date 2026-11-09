import { supportingSingaporeEvaluations } from "./screening";
import type {
  CrossReference,
  IngredientResult,
  RuleConcentration,
  RuleEvaluation,
} from "../types/screening";

const reviewReasonLabels: Record<string, string> = {
  no_source_backed_identity_match: "We could not match this ingredient to a trusted source. Check the name or CAS number.",
  neither_name_nor_cas_resolved_to_a_source_backed_identity: "We could not match the name or CAS number. Check both values.",
  supplied_name_and_cas_resolve_to_different_singapore_identities: "The ingredient name and CAS number point to different substances. Check which one is correct.",
  supplied_name_and_cas_have_multiple_common_singapore_identities: "The name and CAS number still leave more than one possible ingredient. Confirm the correct one.",
  only_one_supplied_identifier_provides_a_unique_corroborated_identity: "Only the name or CAS number matched. Check the other value.",
  supplied_identifiers_do_not_establish_a_unique_singapore_identity: "The submitted details do not identify one clear ingredient. Check the name and CAS number.",
  singapore_identity_bridge_is_not_aligned: "The ACD and Singapore records do not clearly point to the same ingredient. Compare both sources.",
  identifier_matches_multiple_singapore_identities: "This identifier matches more than one Singapore ingredient. Confirm the correct one.",
  exact_identity_exists_only_in_the_acd_snapshot: "This ingredient appears in the ACD source, but its Singapore match is unclear. Compare the sources.",
  supplied_cas_is_malformed: "The CAS number is not in a valid format. Check it.",
  source_wording_or_regulatory_field_differs: "The ACD and Singapore records differ. Compare the source wording before deciding.",
  ambiguous_multi_case_concentration_not_normalized: "This rule has several limits. Confirm which one applies to this product.",
  conditional_prohibition_wording_not_structured: "This rule has an exception that still needs checking.",
  additional_numeric_condition_not_structured: "This rule has another number or limit that the system cannot check automatically.",
  concentration_condition_not_normalized: "The system could not apply this concentration limit automatically. Check the source rule.",
  concentration_contains_multiple_or_ambiguous_values: "The rule lists more than one possible concentration. Confirm which value applies.",
  multi_case_mapping_not_unambiguous: "The rule has several cases, and the system cannot tell which one applies.",
  no_current_singapore_reference_number_match: "The ACD record has no clear matching Singapore reference. Check the current Singapore source.",
  non_exhaustive_identifier_scope_not_structured: "The source describes a group of substances. Check whether this ingredient is included.",
  normalized_case_structure_differs_between_sources: "The ACD and Singapore versions organise the cases differently. Compare them.",
  ranged_reference_prevents_unique_entry_correspondence: "The source uses a range of references, so the exact matching entry is unclear.",
  jurisdiction_specific_source_wording: "The ACD and Singapore wording differs. Check which Singapore wording applies.",
  malformed_cas_identifier_preserved: "The source contains an unusual CAS number. Check it against the original document.",
  blank_deleted_or_ranged_source_entry: "The source entry is blank, deleted, or covers a range and needs checking.",
  catalogue_identity_singapore_linkage_unresolved: "The ingredient name is recognised, but its Singapore identity still needs checking.",
  ingredient_catalogue_unavailable_identity_verification_withheld: "The ingredient-name catalogue is unavailable. Check the identity manually.",
  ingredient_linkage_baseline_unavailable: "The older identity-linkage file is unavailable. Check the identity manually.",
  linkage_not_valid_for_active_baseline: "The saved identity link does not match the current source versions. Check it again.",
  supplied_cas_cannot_be_corroborated_by_catalogue_source: "The ingredient catalogue contains names only, so it cannot confirm the submitted CAS number.",
};

const statusLabels: Record<string, string> = {
  changed: "Changed",
  aligned: "Aligned",
  acd_only: "ACD only",
  singapore_only: "Singapore only",
  ambiguous: "Ambiguous",
  deterministic: "Deterministic",
  withheld_professional_review: "Withheld for professional review",
  withheld_information_missing: "Information missing",
  not_applicable_to_submitted_context: "Not applicable to submitted context",
  resolved: "Resolved",
  unresolved: "Unresolved",
  review_required: "Review required",
  not_applicable: "Not applicable",
  linked: "Linked",
  verified_not_represented: "Verified not represented in scoped lists",
};

const matchMethodLabels: Record<string, string> = {
  exact_name: "Exact source-backed name",
  exact_cas: "Exact source-backed CAS",
  exact_name_via_acd: "Exact name via ACD cross-reference",
  exact_cas_via_acd: "Exact CAS via ACD cross-reference",
  exact_catalogue_name: "Exact EU catalogue name",
  accepted_catalogue_linkage: "Accepted EU-to-Singapore identity linkage",
  accepted_verified_not_represented: "Accepted scoped absence review",
};

const fieldLabels: Record<string, string> = {
  substance_name: "Source substance wording",
  product_context: "Product context",
  concentration: "Concentration",
  other_conditions: "Other requirements",
  required_warning: "Required warning",
};

export function displayIngredientName(result: IngredientResult): string {
  const supportingName = supportingSingaporeEvaluations(result)[0]?.evidence.substance_name;
  const resolvedName = result.identity.singapore_candidates.find(
    (candidate) => candidate.substance_id === result.identity.resolved_singapore_substance_id,
  )?.original_substance_name;
  const sourceBackedName = supportingName ?? resolvedName ?? result.identity.catalogue_identity?.canonical_name;
  if (!sourceBackedName) return result.submitted_ingredient.name;
  const delimiterIndex = sourceBackedName.toLowerCase().indexOf(" (except ");
  return delimiterIndex < 0 ? sourceBackedName : sourceBackedName.slice(0, delimiterIndex);
}

export function reviewTypeLabel(value: string): string {
  return {
    identity_review: "Ingredient identity",
    rule_review: "How the rule applies",
  }[value] ?? readableCode(value);
}

export function readableCode(value: string): string {
  return statusLabels[value] ?? value.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

export function matchMethodLabel(value: string): string {
  return matchMethodLabels[value] ?? readableCode(value);
}

export function reviewReasonLabel(value: string): string {
  const separator = value.indexOf(": ");
  const reason = separator >= 0 ? value.slice(separator + 2) : value;
  if (reason.startsWith("incompatible ")) {
    const fields = reason.slice("incompatible ".length).split(";")[0].split(", ");
    const labels: Record<string, string> = {
      unit: "unit",
      basis: "concentration basis",
      preparation_stage: "preparation stage",
    };
    const readableFields = fields.map((field) => labels[field] ?? readableCode(field).toLowerCase());
    if (readableFields.length === 1 && readableFields[0] === "preparation stage") {
      return "The percentage is for a different preparation stage. Check when this concentration applies.";
    }
    return `The submitted ${readableFields.join(", ")} does not match the rule. Check it before comparing the concentration.`;
  }
  const runtimeReasons: Record<string, string> = {
    "normalized restriction has no executable concentration constraint": "The rule does not contain a limit the system can compare automatically. Check the source rule.",
    "source preparation stage is not sufficiently specified for comparison": "The rule does not clearly say when its concentration limit applies. Check the source wording.",
    "concentration value, unit, basis, and stage are required": "Add the concentration details before this rule can be checked.",
    "unsupported comparator or numerical limit": "The rule's limit cannot be calculated automatically. Check the source value.",
    "other regulatory requirements were returned as evidence but not evaluated": "This rule has other requirements that still need to be checked.",
    "required warning was returned as evidence but not evaluated": "This rule includes a warning that still needs to be checked.",
  };
  if (runtimeReasons[reason]) return runtimeReasons[reason];
  return reviewReasonLabels[reason] ?? readableCode(reason);
}

export function preparationStageLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return {
    finished_product: "Finished product",
    after_mixing: "After mixing for use",
    ready_for_use: "Ready for use",
  }[value] ?? readableCode(value);
}

export function basisLabel(value: string | null | undefined): string {
  return value == null ? "No specific basis" : value;
}

export function comparatorLabel(value: string | undefined): string {
  return {
    less_than_or_equal: "At most",
    less_than: "Less than",
  }[value ?? ""] ?? readableCode(value ?? "Unspecified");
}

export function formatRuleConcentration(value: RuleConcentration | null): string {
  if (!value || typeof value.value !== "number") return value?.source_text ?? "—";
  const unit = value.unit === "percent" ? "%" : ` ${value.unit ?? ""}`;
  return `${value.value}${unit}`;
}

export function acceptedSnapshotLabel(evaluation: RuleEvaluation): string {
  const effectiveDate = evaluation.evidence.effective_date;
  if (effectiveDate) {
    const date = new Date(`${effectiveDate}T00:00:00Z`);
    const formatted = new Intl.DateTimeFormat("en-GB", {
      day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
    }).format(date);
    return `Accepted snapshot · version in force ${formatted}`;
  }
  return `Accepted snapshot · ${evaluation.evidence.source_version ?? evaluation.evidence.document_revision ?? "version recorded in baseline"}`;
}

function stripStructuralMarker(value: unknown): string {
  if (value == null || value === "") return "—";
  const text = typeof value === "string" ? value : String(value);
  return text.replace(/^\[parent\]\s?/, "") || "—";
}

function parseConcentration(value: unknown): RuleConcentration | null {
  const text = stripStructuralMarker(value);
  if (!text.startsWith("{")) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" ? parsed as RuleConcentration : null;
  } catch {
    return null;
  }
}

export interface ComparisonRow {
  field: string;
  acd: string;
  singapore: string;
}

export function comparisonRows(reference: CrossReference): ComparisonRow[] {
  if (reference.requirement_differences) {
    return reference.requirement_differences.map((difference) => ({
      field: fieldLabels[difference.aspect] ?? readableCode(difference.aspect),
      acd: difference.acd,
      singapore: difference.singapore,
    }));
  }
  const rows: ComparisonRow[] = [];
  for (const [field, rawDifference] of Object.entries(reference.field_differences)) {
    const difference = rawDifference && typeof rawDifference === "object"
      ? rawDifference as { acd?: unknown; singapore?: unknown }
      : { acd: rawDifference, singapore: rawDifference };
    if (field === "concentration") {
      const acd = parseConcentration(difference.acd);
      const singapore = parseConcentration(difference.singapore);
      if (acd && singapore) {
        rows.push(
          { field: "Maximum concentration", acd: formatRuleConcentration(acd), singapore: formatRuleConcentration(singapore) },
          { field: "Comparator", acd: comparatorLabel(acd.comparator), singapore: comparatorLabel(singapore.comparator) },
          { field: "Concentration basis", acd: basisLabel(acd.basis), singapore: basisLabel(singapore.basis) },
          { field: "Preparation stage", acd: preparationStageLabel(acd.preparation_stage), singapore: preparationStageLabel(singapore.preparation_stage) },
        );
        continue;
      }
    }
    rows.push({
      field: fieldLabels[field] ?? readableCode(field),
      acd: stripStructuralMarker(difference.acd),
      singapore: stripStructuralMarker(difference.singapore),
    });
  }
  return rows;
}

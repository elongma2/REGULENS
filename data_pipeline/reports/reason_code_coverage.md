# Screening issue-code explanation coverage

Covered issue codes: **28**

| Issue code | Deterministic explanation | Reviewer action |
|---|---|---|
| `additional_condition_unresolved` | The rule contains an additional condition that Regulens cannot evaluate automatically. | Check the additional condition in the source against the formulation. |
| `applicability_condition_not_met` | The submitted product use does not meet a listed condition. | Review the product use against the exact source condition. |
| `applicability_fact_missing` | A product-use fact required by the rule is missing. | Confirm the product-use fact identified by the rule. |
| `combined_limit_information_missing` | The rule limits the combined amount of related constituents, but the complete compatible total is unavailable. | Confirm whether the related constituents are present and verify their combined concentration. |
| `concentration_basis_mismatch` | The submitted concentration and the rule use different concentration bases. | Confirm the concentration using the basis stated in the rule. |
| `concentration_missing` | The applicable rule needs concentration information that was not supplied. | Provide the concentration, unit, basis, and preparation stage required by the rule. |
| `concentration_range_inconclusive` | The reported range or approximate value cannot be conclusively compared with the rule limit. | Confirm an exact concentration or review the full reported interval against the limit. |
| `concentration_rule_not_executable` | The source concentration condition is not represented as one safely executable comparison. | Review the original concentration wording and its applicable branch. |
| `concentration_semantics_incompatible` | The submitted concentration and the rule use incompatible measurement semantics. | Confirm the concentration using the unit, basis, and stage stated in the rule. |
| `concentration_unit_mismatch` | The submitted concentration and the rule use different units. | Confirm the concentration using the unit stated in the rule. |
| `identity_genuine_conflict` | The submitted name and CAS number match different source-backed ingredient identities. | Confirm the correct ingredient name and CAS number. |
| `identity_multiple_candidates` | More than one source-backed identity remains possible. | Confirm the exact ingredient identity from the supplier specification. |
| `identity_related_forms` | The submitted identifiers refer to related chemical forms that are not interchangeable exact identities. | Confirm the exact chemical form supplied. |
| `identity_secondary_identifier_unverified` | One submitted identifier is recognised, but its relationship to the other identifier is not verified. | Verify the name and CAS association against the supplier specification. |
| `identity_unresolved` | Regulens could not establish one source-backed ingredient identity. | Confirm the ingredient name and a reliable identifier. |
| `impurity_trace_requirement` | The rule requires an impurity or degradation product to remain at trace level. | Confirm the impurity or degradation-product level against the source requirement. |
| `inactive_applicability_unresolved` | An inactive source entry has unresolved current applicability. | Confirm the entry's current legal status from the official source. |
| `nano_condition_unresolved` | The rule contains particle-form or nano-specific requirements that remain unevaluated. | Confirm the material form and every nano-specific source condition. |
| `preparation_stage_mismatch` | The submitted concentration is for one stage, but the rule applies at a different stage. | Confirm the concentration at the stage stated in the rule. |
| `product_context_missing` | The rule applies only to a stated product use, but that product information was not supplied. | Confirm the product category or use stated in the rule. |
| `product_context_unverified` | The submitted product description is not an exact source-backed regulatory context. | Select or confirm the applicable source-backed product context. |
| `regulated_function_dataset_incomplete` | The applicable positive-list check is unavailable in the active dataset. | Review the intended function against the current official source. |
| `regulated_function_not_listed` | The ingredient was explicitly submitted for a regulated function but no matching entry was found in that Singapore positive list. | Confirm the intended function and the ingredient identity against the applicable Singapore list. |
| `rule_exception_unresolved` | This rule has an exception that still needs checking. | Check whether the exception shown in the regulatory source applies to this formulation. |
| `rule_normalization_withheld` | The source rule could not be represented as a reliable deterministic check. | Review the original source wording and all listed conditions. |
| `screening_incomplete` | At least one applicable regulatory check was withheld or could not be completed. | Review each unresolved condition before relying on the screening result. |
| `source_difference_material` | The Singapore and ACD source records contain a material difference. | Review both source records and apply the current Singapore requirement. |
| `warning_requirement_unverified` | The source contains a warning requirement whose applicability has not been established. | Check whether the warning condition applies; formulation screening does not confirm the label. |

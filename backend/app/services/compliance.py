from __future__ import annotations

from data_pipeline.scripts.normalize import conservative_text

from backend.app.models.screening import (
    ConditionEvaluation,
    ConditionStatus,
    ConcentrationType,
    Finding,
    FunctionEvaluation,
    IdentityOutcome,
    IdentityStatus,
    IdentityResolution,
    ScreeningDisposition,
    IngredientInput,
    RegulatedFunction,
    ReviewType,
    ReviewIssue,
    ReviewIssueSeverity,
    RuleEvaluation,
    ScreeningResult,
    WarningApplicability,
    WarningRequirement,
)
from backend.app.services.evidence import build_rule_evidence
from backend.app.services.loader import REGULATORY_SEARCH_SCOPE, RegulatoryStore
from backend.app.services.resolver import resolve_ingredient
from backend.app.services.ingredient_catalog import IngredientCatalog
from backend.app.services.evaluation_issues import build_review_issues, disposition_is_incomplete
from backend.app.services.concentration_units import convert_concentration_unit


def _same(value: str | None, expected: str | None) -> bool:
    if value is None or expected is None:
        return value is expected
    return conservative_text(value) == conservative_text(expected)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


FUNCTION_PARTS = {
    RegulatedFunction.COLOURANT: "Third Schedule Part III",
    RegulatedFunction.PRESERVATIVE: "Third Schedule Part IV",
    RegulatedFunction.UV_FILTER: "Third Schedule Part V",
}


def _concentration_relation(submitted, comparator: str, limit: float) -> str:
    """Classify a submitted exact/interval concentration against one upper limit."""
    kind = submitted.concentration_type
    if kind == ConcentrationType.UNKNOWN:
        return "unknown"
    if kind == ConcentrationType.APPROXIMATE:
        return "potential"
    if kind == ConcentrationType.EXACT:
        if comparator == "less_than_or_equal":
            return "within" if submitted.value <= limit else "exceeds"
        return "within" if submitted.value < limit else "exceeds"

    lower = submitted.lower_bound
    upper = submitted.upper_bound
    lower_inclusive = submitted.lower_inclusive is not False
    upper_inclusive = submitted.upper_inclusive is not False

    fully_within = False
    if upper is not None:
        if comparator == "less_than_or_equal":
            fully_within = upper <= limit
        else:
            fully_within = upper < limit or (upper == limit and not upper_inclusive)

    fully_exceeds = False
    if lower is not None:
        if comparator == "less_than_or_equal":
            fully_exceeds = lower > limit or (lower == limit and not lower_inclusive)
        else:
            fully_exceeds = lower >= limit

    if fully_within:
        return "within"
    if fully_exceeds:
        return "exceeds"
    return "potential"


def _material_source_difference(store: RegulatoryStore, rule: dict) -> bool:
    return any(
        reference.get("confirmed_material_difference", False)
        for reference in store.cross_references_by_rule_id.get(rule["rule_id"], ())
    )


def _warning_results(rule: dict, applicable: WarningApplicability) -> list[WarningRequirement]:
    structured = rule.get("warning_requirements", [])
    if not structured and (rule.get("required_warning") or "").strip() not in {"", ".", "-"}:
        structured = [{"warning_text": rule["required_warning"], "trigger_text": None}]
    return [
        WarningRequirement(
            rule_id=rule["rule_id"],
            warning_text=item["warning_text"],
            trigger_text=item.get("trigger_text"),
            applicability=(
                WarningApplicability.UNDETERMINED
                if item.get("applicability") == "professional_review"
                else applicable
            ),
            source_reference=f"{rule['regulatory_section']} reference {rule['reference_number']}",
        )
        for item in structured
    ]


def _has_unstructured_positive_condition(rule: dict) -> bool:
    text = (rule.get("other_conditions") or "").strip()
    if text in {"", ".", "-"}:
        return False
    normalized = conservative_text(text)
    represented_texts = [
        rule.get("product_context"),
        (rule.get("concentration") or {}).get("source_text"),
        *[item.get("source_text") for item in rule.get("applicability_requirements", [])],
        *[item.get("source_text") for item in rule.get("combined_limit_requirements", [])],
    ]
    return normalized not in {
        conservative_text(value)
        for value in represented_texts
        if isinstance(value, str) and value.strip()
    }


def _evaluate_positive_rule(
    store: RegulatoryStore,
    rule: dict,
    ingredient: IngredientInput,
    product_facts: dict[str, bool | None],
    combined_contexts: dict[str, dict] | None = None,
) -> tuple[RuleEvaluation, list[ConditionEvaluation], list[WarningRequirement], Finding | None, list[str], list[str]]:
    evidence = build_rule_evidence(store, rule)
    conditions: list[ConditionEvaluation] = []
    review_reasons: list[str] = []
    missing_reasons: list[str] = []
    if not rule["active"] or rule["normalization_status"] == "inactive_source_entry":
        reason = f"{rule['rule_id']}: positive-list entry is inactive"
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="not_applicable_inactive", reasons=[reason], evidence=evidence),
            conditions,
            [],
            None,
            review_reasons,
            missing_reasons,
        )
    if rule["normalization_status"] != "normalized":
        reasons = rule.get("review_reasons") or ["positive-list conditions require professional review"]
        review_reasons.extend(f"{rule['rule_id']}: {reason}" for reason in reasons)
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_professional_review", reasons=reasons, evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.UNDETERMINED),
            None,
            review_reasons,
            missing_reasons,
        )

    # Some source rows contain mutually exclusive, labelled product branches.
    # A branch selector decides which legal case applies; failing that selector
    # does not mean the product violates the condition in the other branch.
    for requirement in rule.get("applicability_requirements", []):
        if requirement.get("role", "condition") != "case_selector":
            continue
        fact = requirement["fact"]
        actual = product_facts.get(fact)
        if actual is None:
            reason = f"{rule['rule_id']}: Product fact '{fact}' is required to select the applicable source case"
            missing_reasons.append(reason)
            conditions.append(ConditionEvaluation(
                rule_id=rule["rule_id"],
                condition_type=fact,
                status=ConditionStatus.INFORMATION_MISSING,
                source_text=requirement["source_text"],
                reason=reason,
            ))
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_information_missing", reasons=[reason], evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.UNDETERMINED),
                None,
                review_reasons,
                missing_reasons,
            )
        if actual != requirement["expected"]:
            conditions.append(ConditionEvaluation(
                rule_id=rule["rule_id"],
                condition_type=fact,
                status=ConditionStatus.NOT_APPLICABLE,
                source_text=requirement["source_text"],
                reason="A different source case applies to the submitted product.",
            ))
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="not_applicable_to_submitted_context", evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.NOT_APPLICABLE),
                None,
                review_reasons,
                missing_reasons,
            )
        conditions.append(ConditionEvaluation(
            rule_id=rule["rule_id"],
            condition_type=fact,
            status=ConditionStatus.SATISFIED,
            source_text=requirement["source_text"],
        ))

    unresolved_combined = False
    combined_failed = False
    for requirement in rule.get("combined_limit_requirements", []):
        context = (combined_contexts or {}).get(requirement["group_key"])
        if not context or context.get("status") != "complete":
            missing_refs = (context or {}).get("missing_references", requirement.get("constituent_references", []))
            missing_labels: list[str] = []
            for reference in missing_refs:
                source_rule = next((
                    candidate for candidate in store.rules_by_id.values()
                    if candidate.get("regulatory_section") == rule.get("regulatory_section")
                    and candidate.get("reference_number") == reference
                ), None)
                label = source_rule.get("substance_name") if source_rule else None
                missing_labels.append(f"{label} ({reference})" if label else reference)
            reason = (
                f"{rule['rule_id']}: combined concentration limit requires confirmation of "
                f"constituents {', '.join(missing_labels) or ', '.join(requirement.get('constituent_references', []))}"
            )
            review_reasons.append(reason)
            conditions.append(ConditionEvaluation(
                rule_id=rule["rule_id"],
                condition_type="combined_concentration",
                status=ConditionStatus.PROFESSIONAL_REVIEW,
                source_text=requirement["source_text"],
                reason=reason,
            ))
            unresolved_combined = True
            continue
        maximum = requirement["maximum"]
        total = context["total"]
        comparator = maximum["comparator"]
        within = total <= maximum["value"] if comparator == "less_than_or_equal" else total < maximum["value"]
        conditions.append(ConditionEvaluation(
            rule_id=rule["rule_id"],
            condition_type="combined_concentration",
            status=ConditionStatus.SATISFIED if within else ConditionStatus.NOT_SATISFIED,
            source_text=requirement["source_text"],
            reason=f"Combined submitted concentration: {total:g} {maximum['unit']}",
        ))
        combined_failed = combined_failed or not within

    impurity_footnotes = [
        item for item in rule.get("footnotes", [])
        if any(marker in conservative_text(item.get("source_text") or "") for marker in ("impurity", "degradation product", "trace level"))
    ]
    if impurity_footnotes:
        reason = f"{rule['rule_id']}: impurity or degradation-product trace-level requirement requires confirmation"
        review_reasons.append(reason)
        conditions.extend(ConditionEvaluation(
            rule_id=rule["rule_id"],
            condition_type="impurity_or_degradation_product",
            status=ConditionStatus.PROFESSIONAL_REVIEW,
            source_text=item["source_text"],
            reason=reason,
        ) for item in impurity_footnotes)

    failed = False
    missing = False
    for requirement in rule.get("applicability_requirements", []):
        if requirement.get("role", "condition") == "case_selector":
            continue
        fact = requirement["fact"]
        actual = product_facts.get(fact)
        if actual is None:
            status = ConditionStatus.INFORMATION_MISSING
            reason = f"Product fact '{fact}' is required"
            missing = True
            missing_reasons.append(f"{rule['rule_id']}: {reason}")
        elif actual != requirement["expected"]:
            status = ConditionStatus.NOT_SATISFIED
            reason = f"Submitted product fact '{fact}' does not meet the listed use condition"
            failed = True
        else:
            status = ConditionStatus.SATISFIED
            reason = None
        conditions.append(ConditionEvaluation(
            rule_id=rule["rule_id"],
            condition_type=fact,
            status=status,
            source_text=requirement["source_text"],
            reason=reason,
        ))
    if failed:
        finding = Finding.PERMITTED_USE_CONDITION_NOT_MET
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="deterministic_condition_not_met", finding=finding, evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.NOT_APPLICABLE),
            finding,
            review_reasons,
            missing_reasons,
        )
    if combined_failed:
        finding = Finding.PERMITTED_USE_CONDITION_NOT_MET
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="deterministic_condition_not_met", finding=finding, reasons=review_reasons, evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.NOT_APPLICABLE),
            finding,
            review_reasons,
            missing_reasons,
        )
    if missing:
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_information_missing", reasons=missing_reasons, evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.UNDETERMINED),
            None,
            review_reasons,
            missing_reasons,
        )

    if _has_unstructured_positive_condition(rule) and not rule.get("applicability_requirements"):
        reason = f"{rule['rule_id']}: source condition is not represented as a closed deterministic field"
        review_reasons.append(reason)
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_professional_review", reasons=[reason], evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.UNDETERMINED),
            None,
            review_reasons,
            missing_reasons,
        )

    constraint = rule.get("concentration")
    if constraint:
        if ingredient.concentration is None:
            reason = f"{rule['rule_id']}: concentration value, unit, basis, and stage are required"
            missing_reasons.append(reason)
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_information_missing", reasons=[reason], evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.UNDETERMINED),
                None,
                review_reasons,
                missing_reasons,
            )
        submitted = ingredient.concentration
        if submitted.concentration_type == ConcentrationType.UNKNOWN:
            reason = f"{rule['rule_id']}: concentration was not disclosed"
            missing_reasons.append(reason)
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_information_missing", reasons=[reason], submitted_concentration=submitted, evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.UNDETERMINED),
                None,
                review_reasons,
                missing_reasons,
            )
        if submitted.unit is None or submitted.preparation_stage is None:
            reason = f"{rule['rule_id']}: concentration unit and preparation stage are required"
            missing_reasons.append(reason)
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_information_missing", reasons=[reason], submitted_concentration=submitted, evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.UNDETERMINED),
                None,
                review_reasons,
                missing_reasons,
            )
        evaluated = submitted
        conversion_reason: str | None = None
        if not _same(submitted.unit, constraint.get("unit")):
            converted = convert_concentration_unit(submitted, constraint.get("unit"))
            if converted is not None:
                evaluated = converted
                conversion_reason = (
                    f"Converted {submitted.unit} to {constraint.get('unit')} using the exact "
                    "mass-fraction relationship."
                )
        incompatible = [
            field for field in ("unit", "basis", "preparation_stage")
            if not _same(getattr(evaluated, field), constraint.get(field))
        ]
        if incompatible:
            reason = f"{rule['rule_id']}: incompatible " + ", ".join(incompatible) + "; no conversion performed"
            review_reasons.append(reason)
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_professional_review", reasons=[reason], submitted_concentration=submitted, evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.UNDETERMINED),
                None,
                review_reasons,
                missing_reasons,
            )
        comparator = constraint.get("comparator")
        limit = constraint.get("value")
        if comparator not in {"less_than_or_equal", "less_than"} or not isinstance(limit, (int, float)):
            reason = f"{rule['rule_id']}: unsupported positive-list concentration comparison"
            review_reasons.append(reason)
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_professional_review", reasons=[reason], submitted_concentration=submitted, evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.UNDETERMINED),
                None,
                review_reasons,
                missing_reasons,
            )
        relation = _concentration_relation(evaluated, comparator, float(limit))
        if relation == "potential":
            reason = f"{rule['rule_id']}: reported concentration range or approximate value cannot be conclusively compared with the limit"
            review_reasons.append(reason)
            return (
                RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_professional_review", reasons=[reason], submitted_concentration=submitted, evidence=evidence),
                conditions,
                _warning_results(rule, WarningApplicability.UNDETERMINED),
                None,
                review_reasons,
                missing_reasons,
            )
        within = relation == "within"
        finding = Finding.PERMITTED_USE_WITHIN_CONDITIONS if within else Finding.PERMITTED_USE_CONDITION_NOT_MET
        evaluation_status = "withheld_professional_review" if review_reasons or unresolved_combined else "deterministic"
        evaluation_reasons = ([conversion_reason] if conversion_reason else []) + review_reasons
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status=evaluation_status, finding=finding, reasons=evaluation_reasons, submitted_concentration=evaluated, evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.APPLICABLE if within else WarningApplicability.NOT_APPLICABLE),
            finding,
            review_reasons,
            missing_reasons,
        )

    finding = Finding.PERMITTED_USE_WITHIN_CONDITIONS
    return (
        RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_professional_review" if review_reasons else "deterministic", finding=finding, reasons=review_reasons, evidence=evidence),
        conditions,
        _warning_results(rule, WarningApplicability.APPLICABLE),
        finding,
        review_reasons,
        missing_reasons,
    )


def screen_ingredient(
    store: RegulatoryStore,
    ingredient: IngredientInput,
    product_context: str | None = None,
    product_applicability: dict[str, bool | None] | None = None,
    ingredient_catalog: IngredientCatalog | None = None,
    linkage_store=None,
    catalogue_error: str | None = None,
    identity_resolution: IdentityResolution | None = None,
    combined_contexts: dict[str, dict] | None = None,
) -> ScreeningResult:
    product_applicability = product_applicability or {}
    identity = identity_resolution or resolve_ingredient(
        store,
        ingredient.name,
        ingredient.cas_number,
        ingredient_catalog=ingredient_catalog,
        linkage_store=linkage_store,
        catalogue_error=catalogue_error,
    )
    suggestion = ingredient.identity_suggestion
    if suggestion is not None and suggestion.status != "confirmed":
        identity = identity.model_copy(update={
            "status": IdentityStatus.UNRESOLVED,
            "identity_outcome": IdentityOutcome.UNRESOLVED,
            "resolved_singapore_substance_id": None,
            "resolved_singapore_substance_ids": [],
            "applicable_regulatory_record_ids": [],
            "reviewer_action": (
                f"Confirm whether {suggestion.original_name} is the same ingredient as "
                f"{suggestion.canonical_name}, or keep it unidentified."
            ),
            "reasons": [
                *identity.reasons,
                (
                    "ai_identity_suggestion_rejected_by_reviewer"
                    if suggestion.status == "rejected"
                    else "ai_identity_suggestion_requires_reviewer_confirmation"
                ),
            ],
        })
    if identity.status == IdentityStatus.UNRESOLVED:
        issues = build_review_issues(identity, [], identity.reasons)
        return ScreeningResult(
            dataset_version=store.dataset_version,
            accepted_baseline_sha256=store.baseline_manifest_hash,
            submitted_ingredient=ingredient,
            submitted_product_context=product_context,
            identity=identity,
            primary_finding=Finding.IDENTITY_UNRESOLVED,
            screening_disposition=ScreeningDisposition.NOT_EVALUATED_IDENTITY_UNRESOLVED,
            review_required=True,
            review_types=[ReviewType.IDENTITY],
            review_reasons=identity.reasons,
            review_issues=issues,
        )
    if identity.status != IdentityStatus.RESOLVED and not identity.resolved_singapore_substance_ids:
        issues = build_review_issues(identity, [], identity.reasons)
        return ScreeningResult(
            dataset_version=store.dataset_version,
            accepted_baseline_sha256=store.baseline_manifest_hash,
            submitted_ingredient=ingredient,
            submitted_product_context=product_context,
            identity=identity,
            primary_finding=Finding.PROFESSIONAL_REVIEW,
            screening_disposition=ScreeningDisposition.NOT_EVALUATED_IDENTITY_UNRESOLVED,
            review_required=True,
            review_types=[ReviewType.IDENTITY],
            review_reasons=identity.reasons,
            review_issues=issues,
        )

    substance_ids = identity.resolved_singapore_substance_ids
    if not substance_ids and identity.resolved_singapore_substance_id:
        substance_ids = [identity.resolved_singapore_substance_id]
    if not substance_ids and identity.catalogue_identity is not None and not ingredient.regulated_functions:
        return ScreeningResult(
            dataset_version=store.dataset_version,
            accepted_baseline_sha256=store.baseline_manifest_hash,
            submitted_ingredient=ingredient,
            submitted_product_context=product_context,
            identity=identity,
            primary_finding=Finding.NO_ISSUE,
            review_required=False,
            searched_singapore_parts=[section for section in store.regulatory_search_scope if section.startswith("Third Schedule")],
            searched_regulatory_sections=list(store.regulatory_search_scope),
            scope_note=(
                "The ingredient name is recognised in the EU Glossary of Common Ingredient Names. "
                "No matching entry was identified within the Singapore Third Schedule and ACD "
                "sections in the active accepted dataset. This does not "
                "establish ingredient safety, unrestricted use, or overall product compliance."
            ),
        )

    rules_by_id = {
        rule["rule_id"]: rule
        for substance_id in substance_ids
        for rule in store.rules_by_substance_id.get(substance_id, ())
        if rule["regulatory_section"] in {"Third Schedule Part I", "Third Schedule Part II"}
    }
    all_rules = list(rules_by_id.values())
    evaluations: list[RuleEvaluation] = []
    inactive_evidence = []
    confirmed: list[Finding] = []
    review_reasons: list[str] = []
    missing_reasons: list[str] = []
    function_evaluations: list[FunctionEvaluation] = []
    condition_evaluations: list[ConditionEvaluation] = []
    warning_requirements: list[WarningRequirement] = []
    incomplete_functions: list[RegulatedFunction] = []

    submitted_context_key = conservative_text(product_context) if product_context and product_context.strip() else None
    context_is_source_backed = (
        submitted_context_key is None or submitted_context_key in store.source_backed_contexts
    )

    for rule in sorted(all_rules, key=lambda item: item["rule_id"]):
        evidence = build_rule_evidence(store, rule)
        inactive = not rule["active"] or rule["normalization_status"] == "inactive_source_entry"
        if inactive:
            inactive_evidence.append(evidence)
            if rule.get("unresolved_current_applicability"):
                reason = f"{rule['rule_id']}: inactive record has unresolved current applicability"
                review_reasons.append(reason)
                evaluations.append(
                    RuleEvaluation(
                        rule_id=rule["rule_id"],
                        evaluation_status="withheld_professional_review",
                        reasons=[reason],
                        evidence=evidence,
                    )
                )
            continue

        if rule["regulatory_section"] == "Third Schedule Part I":
            if rule["normalization_status"] != "normalized":
                reasons = rule["review_reasons"] or ["prohibition semantics require professional review"]
                review_reasons.extend(f"{rule['rule_id']}: {reason}" for reason in reasons)
                evaluations.append(
                    RuleEvaluation(
                        rule_id=rule["rule_id"],
                        evaluation_status="withheld_professional_review",
                        reasons=reasons,
                        evidence=evidence,
                    )
                )
            else:
                confirmed.append(Finding.PROHIBITED)
                evaluations.append(
                    RuleEvaluation(
                        rule_id=rule["rule_id"],
                        evaluation_status="deterministic",
                        finding=Finding.PROHIBITED,
                        evidence=evidence,
                    )
                )
            continue

        rule_context = rule.get("product_context")
        all_products = rule_context and conservative_text(rule_context) == "all products"
        if rule_context and not all_products:
            if submitted_context_key is None:
                reason = f"{rule['rule_id']}: product context is required"
                missing_reasons.append(reason)
                evaluations.append(
                    RuleEvaluation(
                        rule_id=rule["rule_id"],
                        evaluation_status="withheld_information_missing",
                        reasons=[reason],
                        evidence=evidence,
                    )
                )
                continue
            if rule["normalization_status"] != "normalized":
                reasons = rule["review_reasons"] or ["restriction semantics require professional review"]
                review_reasons.extend(f"{rule['rule_id']}: {reason}" for reason in reasons)
                evaluations.append(
                    RuleEvaluation(
                        rule_id=rule["rule_id"],
                        evaluation_status="withheld_professional_review",
                        reasons=reasons,
                        evidence=evidence,
                    )
                )
                continue
            if not context_is_source_backed:
                reason = f"{rule['rule_id']}: submitted product context is not an exact source-backed context"
                review_reasons.append(reason)
                evaluations.append(
                    RuleEvaluation(
                        rule_id=rule["rule_id"],
                        evaluation_status="withheld_professional_review",
                        reasons=[reason],
                        evidence=evidence,
                    )
                )
                continue
            if submitted_context_key != conservative_text(rule_context):
                evaluations.append(
                    RuleEvaluation(
                        rule_id=rule["rule_id"],
                        evaluation_status="not_applicable_to_submitted_context",
                        evidence=evidence,
                    )
                )
                continue

        if rule["normalization_status"] != "normalized":
            reasons = rule["review_reasons"] or ["restriction semantics require professional review"]
            review_reasons.extend(f"{rule['rule_id']}: {reason}" for reason in reasons)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_professional_review",
                    reasons=reasons,
                    evidence=evidence,
                )
            )
            continue

        constraint = rule.get("concentration")
        if not constraint:
            reason = f"{rule['rule_id']}: normalized restriction has no executable concentration constraint"
            review_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_professional_review",
                    reasons=[reason],
                    evidence=evidence,
                )
            )
            continue
        if not constraint.get("preparation_stage") or conservative_text(constraint["preparation_stage"]) == "unspecified":
            reason = f"{rule['rule_id']}: source preparation stage is not sufficiently specified for comparison"
            review_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_professional_review",
                    reasons=[reason],
                    submitted_concentration=ingredient.concentration,
                    evidence=evidence,
                )
            )
            continue
        if ingredient.concentration is None:
            reason = f"{rule['rule_id']}: concentration value, unit, basis, and stage are required"
            missing_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_information_missing",
                    reasons=[reason],
                    evidence=evidence,
                )
            )
            continue
        submitted = ingredient.concentration
        if submitted.concentration_type == ConcentrationType.UNKNOWN:
            reason = f"{rule['rule_id']}: concentration was not disclosed"
            missing_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_information_missing",
                    reasons=[reason],
                    submitted_concentration=submitted,
                    evidence=evidence,
                )
            )
            continue
        if submitted.unit is None or submitted.preparation_stage is None:
            reason = f"{rule['rule_id']}: concentration unit and preparation stage are required"
            missing_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_information_missing",
                    reasons=[reason],
                    submitted_concentration=submitted,
                    evidence=evidence,
                )
            )
            continue
        evaluated = submitted
        conversion_reason: str | None = None
        if not _same(submitted.unit, constraint.get("unit")):
            converted = convert_concentration_unit(submitted, constraint.get("unit"))
            if converted is not None:
                evaluated = converted
                conversion_reason = (
                    f"Converted {submitted.unit} to {constraint.get('unit')} using the exact "
                    "mass-fraction relationship."
                )
        incompatible = []
        if not _same(evaluated.unit, constraint.get("unit")):
            incompatible.append("unit")
        if not _same(evaluated.basis, constraint.get("basis")):
            incompatible.append("basis")
        if not _same(evaluated.preparation_stage, constraint.get("preparation_stage")):
            incompatible.append("preparation_stage")
        if incompatible:
            reason = f"{rule['rule_id']}: incompatible " + ", ".join(incompatible) + "; no conversion performed"
            review_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_professional_review",
                    reasons=[reason],
                    submitted_concentration=submitted,
                    evidence=evidence,
                )
            )
            continue
        comparator = constraint.get("comparator")
        limit = constraint.get("value")
        if comparator not in {"less_than_or_equal", "less_than"} or not isinstance(limit, (int, float)):
            reason = f"{rule['rule_id']}: unsupported comparator or numerical limit"
            review_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_professional_review",
                    reasons=[reason],
                    submitted_concentration=submitted,
                    evidence=evidence,
                )
            )
            continue
        relation = _concentration_relation(evaluated, comparator, float(limit))
        if relation == "potential":
            reason = f"{rule['rule_id']}: reported concentration range or approximate value cannot be conclusively compared with the limit"
            review_reasons.append(reason)
            evaluations.append(
                RuleEvaluation(
                    rule_id=rule["rule_id"],
                    evaluation_status="withheld_professional_review",
                    reasons=[reason],
                    submitted_concentration=evaluated,
                    evidence=evidence,
                )
            )
            continue
        within = relation == "within"
        finding = Finding.WITHIN_LIMIT if within else Finding.RESTRICTION_EXCEEDED
        confirmed.append(finding)
        ancillary_reasons = []
        if (rule.get("other_conditions") or "").strip():
            ancillary_reasons.append("other regulatory requirements were returned as evidence but not evaluated")
        if (rule.get("required_warning") or "").strip():
            ancillary_reasons.append("required warning was returned as evidence but not evaluated")
        review_reasons.extend(f"{rule['rule_id']}: {reason}" for reason in ancillary_reasons)
        evaluation_reasons = ([conversion_reason] if conversion_reason else []) + ancillary_reasons
        evaluations.append(
            RuleEvaluation(
                rule_id=rule["rule_id"],
                evaluation_status="deterministic",
                finding=finding,
                reasons=evaluation_reasons,
                submitted_concentration=evaluated,
                evidence=evidence,
            )
        )

    positive_rules = {
        rule["rule_id"]: rule
        for substance_id in substance_ids
        for rule in store.rules_by_substance_id.get(substance_id, ())
        if rule.get("permitted_function")
        and rule["regulatory_section"].startswith("Third Schedule")
    }
    # Candidate discovery and legal applicability are deliberately separate.
    # Identity on a positive list does not prove intended function, but an
    # undeclared function must not make the candidate rule disappear either.
    declared_functions = list(dict.fromkeys(ingredient.regulated_functions))
    discovered_functions = sorted(
        {
            RegulatedFunction(rule["permitted_function"])
            for rule in positive_rules.values()
            if rule.get("permitted_function")
        },
        key=lambda item: item.value,
    )
    functions_to_check = list(dict.fromkeys([*declared_functions, *discovered_functions]))

    for function in functions_to_check:
        part = FUNCTION_PARTS[function]
        if function.value not in store.positive_list_functions:
            reason = f"{part} is not included in the active accepted dataset"
            missing_reasons.append(reason)
            incomplete_functions.append(function)
            function_evaluations.append(FunctionEvaluation(
                regulated_function=function,
                singapore_part=part,
                status=ConditionStatus.INFORMATION_MISSING,
                reasons=[reason],
            ))
            continue
        if function == RegulatedFunction.COLOURANT and product_applicability.get("solely_hair_colouring") is True:
            function_evaluations.append(FunctionEvaluation(
                regulated_function=function,
                singapore_part=part,
                status=ConditionStatus.NOT_APPLICABLE,
                reasons=["Regulation 6(3) excludes products intended solely for colouring hair from Part III"],
            ))
            continue
        matching = [rule for rule in positive_rules.values() if rule.get("permitted_function") == function.value]
        if not matching:
            finding = Finding.REGULATED_FUNCTION_NOT_PERMITTED
            confirmed.append(finding)
            reason = f"Resolved ingredient was not found in the complete {part} positive list for confirmed {function.value} use"
            function_evaluations.append(FunctionEvaluation(
                regulated_function=function,
                singapore_part=part,
                status=ConditionStatus.NOT_SATISFIED,
                finding=finding,
                reasons=[reason],
            ))
            continue

        if function not in declared_functions:
            candidate_missing: list[str] = []
            candidate_review: list[str] = []
            candidate_findings: list[Finding] = []
            potentially_applicable = False
            for rule in sorted(matching, key=lambda item: item["rule_id"]):
                evaluation, conditions, warnings, conditional_finding, rule_review, rule_missing = _evaluate_positive_rule(
                    store, rule, ingredient, product_applicability, combined_contexts
                )
                condition_evaluations.extend(conditions)
                # Until intended use is confirmed, source warnings are
                # candidates rather than established label requirements.
                warning_requirements.extend(
                    warning.model_copy(update={"applicability": WarningApplicability.UNDETERMINED})
                    for warning in warnings
                )
                if evaluation.evaluation_status in {
                    "not_applicable_inactive",
                    "not_applicable_to_submitted_context",
                }:
                    evaluations.append(evaluation)
                    continue

                potentially_applicable = True
                candidate_review.extend(rule_review)
                candidate_missing.extend(rule_missing)
                evaluations.append(evaluation)
                if conditional_finding:
                    confirmed.append(conditional_finding)
                    candidate_findings.append(conditional_finding)
                if _material_source_difference(store, rule):
                    difference = f"{rule['rule_id']}: confirmed material Singapore-ACD requirement difference requires professional review"
                    candidate_review.append(difference)

            review_reasons.extend(candidate_review)
            missing_reasons.extend(candidate_missing)
            if Finding.PERMITTED_USE_CONDITION_NOT_MET in candidate_findings:
                candidate_status = ConditionStatus.NOT_SATISFIED
                candidate_finding = Finding.PERMITTED_USE_CONDITION_NOT_MET
            elif candidate_review:
                candidate_status = ConditionStatus.PROFESSIONAL_REVIEW
                candidate_finding = None
            elif candidate_missing:
                candidate_status = ConditionStatus.INFORMATION_MISSING
                candidate_finding = None
            elif potentially_applicable:
                candidate_status = ConditionStatus.SATISFIED
                candidate_finding = Finding.PERMITTED_USE_WITHIN_CONDITIONS
            else:
                candidate_status = ConditionStatus.NOT_APPLICABLE
                candidate_finding = None
            function_evaluations.append(FunctionEvaluation(
                regulated_function=function,
                singapore_part=part,
                status=candidate_status,
                finding=candidate_finding,
                rule_ids=[rule["rule_id"] for rule in matching],
                reasons=_dedupe(candidate_review + candidate_missing),
            ))
            continue

        function_findings: list[Finding] = []
        function_review: list[str] = []
        function_missing: list[str] = []
        for rule in sorted(matching, key=lambda item: item["rule_id"]):
            evaluation, conditions, warnings, finding, rule_review, rule_missing = _evaluate_positive_rule(
                store, rule, ingredient, product_applicability, combined_contexts
            )
            evaluations.append(evaluation)
            condition_evaluations.extend(conditions)
            warning_requirements.extend(warnings)
            review_reasons.extend(rule_review)
            missing_reasons.extend(rule_missing)
            function_review.extend(rule_review)
            function_missing.extend(rule_missing)
            if finding:
                confirmed.append(finding)
                function_findings.append(finding)
            if (
                evaluation.evaluation_status != "not_applicable_to_submitted_context"
                and _material_source_difference(store, rule)
            ):
                reason = f"{rule['rule_id']}: confirmed material Singapore-ACD requirement difference requires professional review"
                review_reasons.append(reason)
                function_review.append(reason)
        if Finding.PERMITTED_USE_CONDITION_NOT_MET in function_findings:
            function_status = ConditionStatus.NOT_SATISFIED
            function_finding = Finding.PERMITTED_USE_CONDITION_NOT_MET
        elif function_review:
            function_status = ConditionStatus.PROFESSIONAL_REVIEW
            function_finding = None
        elif function_missing:
            function_status = ConditionStatus.INFORMATION_MISSING
            function_finding = None
        else:
            function_status = ConditionStatus.SATISFIED
            function_finding = Finding.PERMITTED_USE_WITHIN_CONDITIONS
        function_evaluations.append(FunctionEvaluation(
            regulated_function=function,
            singapore_part=part,
            status=function_status,
            finding=function_finding,
            rule_ids=[rule["rule_id"] for rule in matching],
            reasons=_dedupe(function_review + function_missing),
        ))

    confirmed = list(dict.fromkeys(confirmed))
    identity_review_reasons = identity.reasons if identity.status != IdentityStatus.RESOLVED else []
    if Finding.PROHIBITED in confirmed:
        primary = Finding.PROHIBITED
    elif Finding.REGULATED_FUNCTION_NOT_PERMITTED in confirmed:
        primary = Finding.REGULATED_FUNCTION_NOT_PERMITTED
    elif Finding.PERMITTED_USE_CONDITION_NOT_MET in confirmed:
        primary = Finding.PERMITTED_USE_CONDITION_NOT_MET
    elif Finding.RESTRICTION_EXCEEDED in confirmed:
        primary = Finding.RESTRICTION_EXCEEDED
    elif review_reasons or identity_review_reasons:
        primary = Finding.PROFESSIONAL_REVIEW
    elif missing_reasons:
        primary = Finding.INFORMATION_MISSING
    elif Finding.WITHIN_LIMIT in confirmed:
        primary = Finding.WITHIN_LIMIT
    elif Finding.PERMITTED_USE_WITHIN_CONDITIONS in confirmed:
        primary = Finding.PERMITTED_USE_WITHIN_CONDITIONS
    else:
        primary = Finding.NO_ISSUE

    review_issues = build_review_issues(
        identity,
        evaluations,
        _dedupe(review_reasons),
        _dedupe(missing_reasons),
    )
    for function_evaluation in function_evaluations:
        if function_evaluation.finding == Finding.REGULATED_FUNCTION_NOT_PERMITTED:
            review_issues.append(ReviewIssue(
                code="regulated_function_not_listed",
                severity=ReviewIssueSeverity.CONDITION_NOT_MET,
                scope="function",
                message=(
                    f"The ingredient was explicitly submitted for use as {function_evaluation.regulated_function.value.replace('_', ' ')}, "
                    f"but no matching entry was found in {function_evaluation.singapore_part}."
                ),
                reviewer_action="Confirm the intended function and ingredient identity against the applicable Singapore positive list.",
                source_reference=function_evaluation.singapore_part,
            ))
    if disposition_is_incomplete(evaluations) or missing_reasons or review_reasons:
        disposition = ScreeningDisposition.PARTIALLY_EVALUATED
    elif identity_review_reasons:
        disposition = ScreeningDisposition.EVALUATED_WITH_IDENTITY_REVIEW
    else:
        disposition = ScreeningDisposition.FULLY_EVALUATED

    return ScreeningResult(
        dataset_version=store.dataset_version,
        accepted_baseline_sha256=store.baseline_manifest_hash,
        submitted_ingredient=ingredient,
        submitted_product_context=product_context,
        identity=identity,
        primary_finding=primary,
        confirmed_findings=confirmed,
        screening_disposition=disposition,
        review_required=bool(review_reasons or identity_review_reasons),
        review_types=(
            ([ReviewType.IDENTITY] if identity_review_reasons else [])
            + ([ReviewType.RULE] if review_reasons else [])
        ),
        review_reasons=_dedupe(identity_review_reasons + review_reasons),
        review_issues=review_issues,
        rule_evaluations=evaluations,
        inactive_evidence=inactive_evidence,
        searched_singapore_parts=[section for section in store.regulatory_search_scope if section.startswith("Third Schedule")],
        searched_regulatory_sections=list(store.regulatory_search_scope),
        function_evaluations=function_evaluations,
        condition_evaluations=condition_evaluations,
        warning_requirements=warning_requirements,
        incomplete_positive_list_checks=list(dict.fromkeys(incomplete_functions)),
    )

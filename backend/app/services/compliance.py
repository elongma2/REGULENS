from __future__ import annotations

from data_pipeline.scripts.normalize import conservative_text

from backend.app.models.screening import (
    ConditionEvaluation,
    ConditionStatus,
    Finding,
    FunctionEvaluation,
    IdentityStatus,
    IngredientInput,
    RegulatedFunction,
    ReviewType,
    RuleEvaluation,
    ScreeningResult,
    WarningApplicability,
    WarningRequirement,
)
from backend.app.services.evidence import build_rule_evidence
from backend.app.services.loader import REGULATORY_SEARCH_SCOPE, RegulatoryStore
from backend.app.services.resolver import resolve_ingredient
from backend.app.services.ingredient_catalog import IngredientCatalog


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


def _material_source_difference(store: RegulatoryStore, rule: dict) -> bool:
    return any(
        reference.get("material_difference", reference.get("comparison_status") != "aligned")
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

    if rule.get("combined_limit_requirements"):
        reason = f"{rule['rule_id']}: combined concentration limit requires formulation-level constituent evaluation"
        review_reasons.append(reason)
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="withheld_professional_review", reasons=[reason], evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.UNDETERMINED),
            None,
            review_reasons,
            missing_reasons,
        )

    failed = False
    missing = False
    for requirement in rule.get("applicability_requirements", []):
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
        incompatible = [
            field for field in ("unit", "basis", "preparation_stage")
            if not _same(getattr(submitted, field), constraint.get(field))
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
        within = submitted.value <= limit if comparator == "less_than_or_equal" else submitted.value < limit
        finding = Finding.PERMITTED_USE_WITHIN_CONDITIONS if within else Finding.PERMITTED_USE_CONDITION_NOT_MET
        return (
            RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="deterministic", finding=finding, submitted_concentration=submitted, evidence=evidence),
            conditions,
            _warning_results(rule, WarningApplicability.APPLICABLE if within else WarningApplicability.NOT_APPLICABLE),
            finding,
            review_reasons,
            missing_reasons,
        )

    finding = Finding.PERMITTED_USE_WITHIN_CONDITIONS
    return (
        RuleEvaluation(rule_id=rule["rule_id"], evaluation_status="deterministic", finding=finding, evidence=evidence),
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
    catalogue_error: str | None = None,
) -> ScreeningResult:
    product_applicability = product_applicability or {}
    identity = resolve_ingredient(
        store,
        ingredient.name,
        ingredient.cas_number,
        ingredient_catalog=ingredient_catalog,
        catalogue_error=catalogue_error,
    )
    if identity.status == IdentityStatus.UNRESOLVED:
        return ScreeningResult(
            dataset_version=store.dataset_version,
            accepted_baseline_sha256=store.baseline_manifest_hash,
            submitted_ingredient=ingredient,
            submitted_product_context=product_context,
            identity=identity,
            primary_finding=Finding.IDENTITY_UNRESOLVED,
            review_required=True,
            review_types=[ReviewType.IDENTITY],
            review_reasons=identity.reasons,
        )
    if identity.status != IdentityStatus.RESOLVED:
        return ScreeningResult(
            dataset_version=store.dataset_version,
            accepted_baseline_sha256=store.baseline_manifest_hash,
            submitted_ingredient=ingredient,
            submitted_product_context=product_context,
            identity=identity,
            primary_finding=Finding.PROFESSIONAL_REVIEW,
            review_required=True,
            review_types=[ReviewType.IDENTITY],
            review_reasons=identity.reasons,
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
        incompatible = []
        if not _same(submitted.unit, constraint.get("unit")):
            incompatible.append("unit")
        if not _same(submitted.basis, constraint.get("basis")):
            incompatible.append("basis")
        if not _same(submitted.preparation_stage, constraint.get("preparation_stage")):
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
        within = submitted.value <= limit if comparator == "less_than_or_equal" else submitted.value < limit
        finding = Finding.WITHIN_LIMIT if within else Finding.RESTRICTION_EXCEEDED
        confirmed.append(finding)
        ancillary_reasons = []
        if (rule.get("other_conditions") or "").strip():
            ancillary_reasons.append("other regulatory requirements were returned as evidence but not evaluated")
        if (rule.get("required_warning") or "").strip():
            ancillary_reasons.append("required warning was returned as evidence but not evaluated")
        review_reasons.extend(f"{rule['rule_id']}: {reason}" for reason in ancillary_reasons)
        evaluations.append(
            RuleEvaluation(
                rule_id=rule["rule_id"],
                evaluation_status="deterministic",
                finding=finding,
                reasons=ancillary_reasons,
                submitted_concentration=submitted,
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
    declared_functions = list(dict.fromkeys(ingredient.regulated_functions))
    if not declared_functions:
        inferred_material = sorted(
            {RegulatedFunction(rule["permitted_function"]) for rule in positive_rules.values()},
            key=lambda value: value.value,
        )
        for function in inferred_material:
            incomplete_functions.append(function)
            reason = f"{function.value} function is not confirmed, so the applicable positive-list check is incomplete"
            missing_reasons.append(reason)
            function_evaluations.append(FunctionEvaluation(
                regulated_function=function,
                singapore_part=FUNCTION_PARTS[function],
                status=ConditionStatus.INFORMATION_MISSING,
                reasons=[reason],
            ))

    for function in declared_functions:
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
        function_findings: list[Finding] = []
        function_review: list[str] = []
        function_missing: list[str] = []
        for rule in sorted(matching, key=lambda item: item["rule_id"]):
            evaluation, conditions, warnings, finding, rule_review, rule_missing = _evaluate_positive_rule(
                store, rule, ingredient, product_applicability
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
            if _material_source_difference(store, rule):
                reason = f"{rule['rule_id']}: material Singapore-ACD source difference requires professional review"
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
    if Finding.PROHIBITED in confirmed:
        primary = Finding.PROHIBITED
    elif Finding.REGULATED_FUNCTION_NOT_PERMITTED in confirmed:
        primary = Finding.REGULATED_FUNCTION_NOT_PERMITTED
    elif Finding.PERMITTED_USE_CONDITION_NOT_MET in confirmed:
        primary = Finding.PERMITTED_USE_CONDITION_NOT_MET
    elif Finding.RESTRICTION_EXCEEDED in confirmed:
        primary = Finding.RESTRICTION_EXCEEDED
    elif review_reasons:
        primary = Finding.PROFESSIONAL_REVIEW
    elif missing_reasons:
        primary = Finding.INFORMATION_MISSING
    elif Finding.WITHIN_LIMIT in confirmed:
        primary = Finding.WITHIN_LIMIT
    elif Finding.PERMITTED_USE_WITHIN_CONDITIONS in confirmed:
        primary = Finding.PERMITTED_USE_WITHIN_CONDITIONS
    else:
        primary = Finding.NO_ISSUE

    return ScreeningResult(
        dataset_version=store.dataset_version,
        accepted_baseline_sha256=store.baseline_manifest_hash,
        submitted_ingredient=ingredient,
        submitted_product_context=product_context,
        identity=identity,
        primary_finding=primary,
        confirmed_findings=confirmed,
        review_required=bool(review_reasons),
        review_types=([ReviewType.RULE] if review_reasons else []),
        review_reasons=_dedupe(review_reasons),
        rule_evaluations=evaluations,
        inactive_evidence=inactive_evidence,
        searched_singapore_parts=[section for section in store.regulatory_search_scope if section.startswith("Third Schedule")],
        searched_regulatory_sections=list(store.regulatory_search_scope),
        function_evaluations=function_evaluations,
        condition_evaluations=condition_evaluations,
        warning_requirements=warning_requirements,
        incomplete_positive_list_checks=list(dict.fromkeys(incomplete_functions)),
    )

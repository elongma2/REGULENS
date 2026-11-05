from __future__ import annotations

import re
from collections.abc import Iterable

from backend.app.models.screening import (
    IdentityOutcome,
    IdentityResolution,
    ReviewIssue,
    ReviewIssueSeverity,
    RuleEvaluation,
)


ISSUE_TEMPLATES: dict[str, tuple[str, str]] = {
    "identity_genuine_conflict": ("The submitted name and CAS number match different source-backed ingredient identities.", "Confirm the correct ingredient name and CAS number."),
    "identity_related_forms": ("The submitted identifiers refer to related chemical forms that are not interchangeable exact identities.", "Confirm the exact chemical form supplied."),
    "identity_multiple_candidates": ("More than one source-backed identity remains possible.", "Confirm the exact ingredient identity from the supplier specification."),
    "identity_unresolved": ("Regulens could not establish one source-backed ingredient identity.", "Confirm the ingredient name and a reliable identifier."),
    "identity_secondary_identifier_unverified": ("One submitted identifier is recognised, but its relationship to the other identifier is not verified.", "Verify the name and CAS association against the supplier specification."),
    "product_context_missing": ("The rule applies only to a stated product use, but that product information was not supplied.", "Confirm the product category or use stated in the rule."),
    "product_context_unverified": ("The submitted product description is not an exact source-backed regulatory context.", "Select or confirm the applicable source-backed product context."),
    "concentration_missing": ("The applicable rule needs concentration information that was not supplied.", "Provide the concentration, unit, basis, and preparation stage required by the rule."),
    "concentration_semantics_incompatible": ("The submitted concentration and the rule use incompatible measurement semantics.", "Confirm the concentration using the unit, basis, and stage stated in the rule."),
    "preparation_stage_mismatch": ("The submitted concentration is for one stage, but the rule applies at a different stage.", "Confirm the concentration at the stage stated in the rule."),
    "concentration_unit_mismatch": ("The submitted concentration and the rule use different units.", "Confirm the concentration using the unit stated in the rule."),
    "concentration_basis_mismatch": ("The submitted concentration and the rule use different concentration bases.", "Confirm the concentration using the basis stated in the rule."),
    "concentration_range_inconclusive": ("The reported range or approximate value cannot be conclusively compared with the rule limit.", "Confirm an exact concentration or review the full reported interval against the limit."),
    "concentration_rule_not_executable": ("The source concentration condition is not represented as one safely executable comparison.", "Review the original concentration wording and its applicable branch."),
    "combined_limit_information_missing": ("The rule limits the combined amount of related constituents, but the complete compatible total is unavailable.", "Confirm whether the related constituents are present and verify their combined concentration."),
    "applicability_fact_missing": ("A product-use fact required by the rule is missing.", "Confirm the product-use fact identified by the rule."),
    "applicability_condition_not_met": ("The submitted product use does not meet a listed condition.", "Review the product use against the exact source condition."),
    "additional_condition_unresolved": ("The rule contains an additional condition that Regulens cannot evaluate automatically.", "Check the additional condition in the source against the formulation."),
    "rule_exception_unresolved": ("This rule has an exception that still needs checking.", "Check whether the exception shown in the regulatory source applies to this formulation."),
    "impurity_trace_requirement": ("The rule requires an impurity or degradation product to remain at trace level.", "Confirm the impurity or degradation-product level against the source requirement."),
    "nano_condition_unresolved": ("The rule contains particle-form or nano-specific requirements that remain unevaluated.", "Confirm the material form and every nano-specific source condition."),
    "warning_requirement_unverified": ("The source contains a warning requirement whose applicability has not been established.", "Check whether the warning condition applies; formulation screening does not confirm the label."),
    "regulated_function_not_listed": ("The ingredient was explicitly submitted for a regulated function but no matching entry was found in that Singapore positive list.", "Confirm the intended function and the ingredient identity against the applicable Singapore list."),
    "regulated_function_dataset_incomplete": ("The applicable positive-list check is unavailable in the active dataset.", "Review the intended function against the current official source."),
    "source_difference_material": ("The Singapore and ACD source records contain a material difference.", "Review both source records and apply the current Singapore requirement."),
    "rule_normalization_withheld": ("The source rule could not be represented as a reliable deterministic check.", "Review the original source wording and all listed conditions."),
    "inactive_applicability_unresolved": ("An inactive source entry has unresolved current applicability.", "Confirm the entry's current legal status from the official source."),
    "screening_incomplete": ("At least one applicable regulatory check was withheld or could not be completed.", "Review each unresolved condition before relying on the screening result."),
}

ISSUE_PRIORITY = {
    "identity_genuine_conflict": 10,
    "identity_related_forms": 11,
    "identity_multiple_candidates": 12,
    "identity_unresolved": 13,
    "identity_secondary_identifier_unverified": 14,
    "screening_incomplete": 20,
    "concentration_missing": 30,
    "product_context_missing": 31,
    "applicability_fact_missing": 32,
    "concentration_range_inconclusive": 33,
    "concentration_semantics_incompatible": 34,
    "preparation_stage_mismatch": 35,
    "concentration_unit_mismatch": 36,
    "concentration_basis_mismatch": 37,
    "combined_limit_information_missing": 40,
    "impurity_trace_requirement": 41,
    "nano_condition_unresolved": 42,
    "rule_exception_unresolved": 43,
    "warning_requirement_unverified": 44,
    "source_difference_material": 90,
}


def _code(reason: str) -> str:
    value = reason.casefold()
    if "combined concentration" in value or "combined use" in value:
        return "combined_limit_information_missing"
    if "impurity" in value or "degradation product" in value or "trace level" in value:
        return "impurity_trace_requirement"
    if "nano" in value or "particle" in value:
        return "nano_condition_unresolved"
    if "product context is required" in value or "product fact" in value and "required" in value:
        return "product_context_missing" if "context" in value else "applicability_fact_missing"
    if "not an exact source-backed context" in value:
        return "product_context_unverified"
    if "does not meet the listed use condition" in value:
        return "applicability_condition_not_met"
    if "concentration was not disclosed" in value or "concentration value" in value or "unit and preparation stage are required" in value:
        return "concentration_missing"
    if "incompatible" in value and "preparation_stage" in value:
        return "preparation_stage_mismatch"
    if "incompatible" in value and "unit" in value:
        return "concentration_unit_mismatch"
    if "incompatible" in value and "basis" in value:
        return "concentration_basis_mismatch"
    if "incompatible" in value:
        return "concentration_semantics_incompatible"
    if "range or approximate" in value:
        return "concentration_range_inconclusive"
    if "unsupported comparator" in value or "no executable concentration" in value or "concentration_not_normalized" in value or "multi_case" in value:
        return "concentration_rule_not_executable"
    if "material singapore-acd" in value:
        return "source_difference_material"
    if "positive-list entry is inactive" in value or "inactive record" in value:
        return "inactive_applicability_unresolved"
    if "not included in the active accepted dataset" in value:
        return "regulated_function_dataset_incomplete"
    if "not found in the complete" in value:
        return "regulated_function_not_listed"
    if "required warning" in value:
        return "warning_requirement_unverified"
    if "conditional" in value or "exception" in value:
        return "rule_exception_unresolved"
    if "other regulatory requirements" in value or "additional" in value or "condition" in value or "semantics require professional review" in value:
        return "additional_condition_unresolved"
    return "rule_normalization_withheld"


def _rule_id(reason: str, evaluations: dict[str, RuleEvaluation]) -> str | None:
    prefix = reason.split(":", 1)[0]
    return prefix if prefix in evaluations else None


def build_review_issues(
    identity: IdentityResolution,
    evaluations: Iterable[RuleEvaluation],
    review_reasons: Iterable[str],
    missing_reasons: Iterable[str] = (),
) -> list[ReviewIssue]:
    by_rule = {item.rule_id: item for item in evaluations}
    issues: list[ReviewIssue] = []

    if identity.status != "resolved":
        outcome = identity.identity_outcome
        if outcome == IdentityOutcome.GENUINE_NAME_CAS_CONFLICT:
            code = "identity_genuine_conflict"
        elif outcome in {IdentityOutcome.RELATED_DISTINCT_FORMS, IdentityOutcome.FORM_RELATIONSHIP_UNRESOLVED}:
            code = "identity_related_forms"
        elif outcome == IdentityOutcome.MULTIPLE_POSSIBLE_IDENTITIES:
            code = "identity_multiple_candidates"
        elif outcome in {IdentityOutcome.NAME_RECOGNISED_CAS_UNVERIFIED, IdentityOutcome.CAS_RECOGNISED_NAME_UNVERIFIED}:
            code = "identity_secondary_identifier_unverified"
        else:
            code = "identity_unresolved"
        message, action = ISSUE_TEMPLATES[code]
        issues.append(ReviewIssue(
            code=code,
            severity=ReviewIssueSeverity.PROFESSIONAL_REVIEW,
            scope="identity",
            message=message,
            reviewer_action=identity.reviewer_action or action,
            related_rule_ids=identity.applicable_regulatory_record_ids,
        ))

    for reason, severity in [
        *((value, ReviewIssueSeverity.PROFESSIONAL_REVIEW) for value in review_reasons),
        *((value, ReviewIssueSeverity.INFORMATION_MISSING) for value in missing_reasons),
    ]:
        code = _code(reason)
        message, action = ISSUE_TEMPLATES[code]
        rule_id = _rule_id(reason, by_rule)
        evaluation = by_rule.get(rule_id) if rule_id else None
        source_reference = None
        related_constituents: list[str] = []
        missing_facts: list[str] = []
        if evaluation:
            source_reference = f"{evaluation.evidence.regulatory_section} Ref {evaluation.evidence.reference_number}"
            related_constituents = [
                reference
                for requirement in evaluation.evidence.combined_limit_requirements
                for reference in requirement.get("constituent_references", [])
            ]
        if code == "combined_limit_information_missing" and ": " in reason:
            detail = reason.split(": ", 1)[1]
            message = detail[:1].upper() + detail[1:] + ("" if detail.endswith(".") else ".")
            action = "Confirm whether each named related constituent is present and verify their compatible combined concentration."
        if code == "applicability_fact_missing":
            if fact_match := re.search(r"Product fact '([^']+)'", reason):
                fact = fact_match.group(1)
                missing_facts = [fact]
                readable = fact.replace("_", " ")
                message = f"The applicable rule needs confirmation of {readable}."
                action = f"Confirm the product's {readable} for the condition stated in the source."
        issues.append(ReviewIssue(
            code=code,
            severity=severity,
            scope="source_comparison" if code == "source_difference_material" else "function" if code.startswith("regulated_function") else "rule",
            message=message,
            reviewer_action=action,
            rule_id=rule_id,
            source_reference=source_reference,
            related_constituent_references=list(dict.fromkeys(related_constituents)),
            missing_facts=missing_facts,
        ))

    # Conditional branches of one legal reference often repeat the same
    # unresolved requirement. Deduplicate by the legal/semantic obligation,
    # not by internal case-rule ID, while retaining every contributing rule.
    deduped: dict[tuple[object, ...], ReviewIssue] = {}
    for issue in issues:
        key = (
            issue.code,
            issue.scope,
            issue.source_reference,
            " ".join(issue.reviewer_action.casefold().split()),
            tuple(sorted(issue.missing_facts)),
            tuple(sorted(issue.related_constituent_references)),
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = issue.model_copy(update={
                "related_rule_ids": list(dict.fromkeys([
                    *issue.related_rule_ids,
                    *([issue.rule_id] if issue.rule_id else []),
                ])),
            })
            continue
        deduped[key] = existing.model_copy(update={
            "related_rule_ids": list(dict.fromkeys([
                *existing.related_rule_ids,
                *issue.related_rule_ids,
                *([issue.rule_id] if issue.rule_id else []),
            ])),
        })
    return sorted(deduped.values(), key=lambda item: (ISSUE_PRIORITY.get(item.code, 60), item.source_reference or "", item.code))


def disposition_is_incomplete(evaluations: Iterable[RuleEvaluation]) -> bool:
    return any(item.evaluation_status.startswith("withheld_") for item in evaluations)


def unmapped_issue_codes() -> set[str]:
    return {code for code, (message, action) in ISSUE_TEMPLATES.items() if not message or not action}

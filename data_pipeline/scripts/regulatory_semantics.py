from __future__ import annotations

import json
import re
import hashlib
from collections.abc import Iterable
from collections.abc import Callable
from typing import Any

from .normalize import conservative_text


_HEADER_MARKERS = (
    "substance identification",
    "maximum concentration",
    "other limitations and requirements",
    "conditions of use and warnings",
    "field of application",
)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip(" .-|\n\t")
    if not text:
        return None
    normalized = conservative_text(text)
    marker_count = sum(marker in normalized for marker in _HEADER_MARKERS)
    if (
        marker_count >= 2
        or "subs tance b" in normalized
        or normalized.startswith("conditions of use and warnings which must be printed on the label")
        or normalized in {"limitations and requirements d", "other limitations and requirements d"}
    ):
        return None
    return normalized


def _without_source_wording(value: Any) -> Any:
    """Keep executable meaning while discarding extraction wording and layout."""
    if isinstance(value, dict):
        return {
            key: _without_source_wording(item)
            for key, item in sorted(value.items())
            if key not in {"source_text", "raw_text", "source_page", "source_pages", "source_field"}
            and _without_source_wording(item) not in (None, "", [], {})
        }
    if isinstance(value, list):
        cleaned = [_without_source_wording(item) for item in value]
        return sorted(
            (item for item in cleaned if item not in (None, "", [], {})),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, str):
        return _clean_text(value)
    return value


def _clean_warning(value: dict[str, Any]) -> dict[str, Any] | None:
    warning = _clean_text(value.get("warning_text"))
    trigger = _clean_text(value.get("trigger_text"))
    if not warning and not trigger:
        return None
    return {
        key: item
        for key, item in {
            "warning_text": warning,
            "trigger_text": trigger,
        }.items()
        if item is not None
    }


def _semantic_rule(rule: dict[str, Any]) -> dict[str, Any]:
    concentration = _without_source_wording(rule.get("concentration"))
    warnings = [
        warning
        for item in rule.get("warning_requirements", [])
        if (warning := _clean_warning(item)) is not None
    ]
    if not warnings:
        required_warning = _clean_text(rule.get("required_warning"))
        if required_warning:
            warnings = [{"warning_text": required_warning}]
    other_conditions = _clean_text(rule.get("other_conditions"))
    return {
        "case_label": _clean_text(rule.get("case_label")) or "parent",
        "concentration_limit": concentration,
        "permitted_function": _clean_text(rule.get("permitted_function")),
        "product_category": _clean_text(rule.get("product_context")),
        "applicability_requirements": _without_source_wording(rule.get("applicability_requirements", [])),
        "combined_limit_requirements": _without_source_wording(rule.get("combined_limit_requirements", [])),
        "mandatory_warnings": _without_source_wording(warnings),
        "effective_date": rule.get("effective_date"),
        "unstructured_conditions": other_conditions,
    }


def _semantic_group(rules: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_semantic_rule(rule) for rule in rules),
        key=lambda item: json.dumps(item, sort_keys=True, default=str),
    )


def _display(value: Any) -> str:
    if value in (None, "", [], {}):
        return "None"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def validate_regulatory_comparison(
    reference: dict[str, Any],
    rules_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare regulatory obligations, not source typography or extraction metadata.

    AI interpretation can be stored on a reference as ``ai_semantic_interpretation``.
    It is used only to resolve wording equivalence; confirmed legal differences still
    require a deterministic difference in structured regulatory data.
    """
    acd_rules = [rules_by_id[rule_id] for rule_id in reference.get("acd_rule_ids", []) if rule_id in rules_by_id]
    singapore_rules = [rules_by_id[rule_id] for rule_id in reference.get("singapore_rule_ids", []) if rule_id in rules_by_id]
    citations = [
        {
            "jurisdiction": jurisdiction,
            "rule_id": rule["rule_id"],
            "section": rule["regulatory_section"],
            "reference_number": rule["reference_number"],
            "source_url": rule.get("source_url"),
            "source_pages": rule.get("source_pages", []),
        }
        for jurisdiction, rules in (("ACD", acd_rules), ("Singapore", singapore_rules))
        for rule in rules
    ]
    if not acd_rules or not singapore_rules:
        return {
            **reference,
            "material_difference": False,
            "professional_review_required": True,
            "semantic_comparison_status": "verification_required",
            "confirmed_material_difference": False,
            "requirement_differences": [],
            "comparison_summary": "No one-to-one Singapore and ACD entry is available for a reliable requirement comparison.",
            "verification_needed": "Verify whether the unmatched entry has a current counterpart before treating it as a regulatory difference.",
            "comparison_method": "deterministic_semantic_validation",
            "comparison_citations": citations,
        }

    acd = _semantic_group(acd_rules)
    singapore = _semantic_group(singapore_rules)
    hard_fields = (
        "concentration_limit",
        "permitted_function",
        "applicability_requirements",
        "combined_limit_requirements",
        "effective_date",
    )
    differences: list[dict[str, str]] = []
    uncertain: list[str] = []
    if len(acd) != len(singapore):
        uncertain.append("the sources use a different number of regulatory cases")
    for index in range(min(len(acd), len(singapore))):
        for field in hard_fields:
            if field == "effective_date" and not (acd[index].get(field) and singapore[index].get(field)):
                continue
            if acd[index].get(field) != singapore[index].get(field):
                differences.append({
                    "aspect": field,
                    "acd": _display(acd[index].get(field)),
                    "singapore": _display(singapore[index].get(field)),
                    "effect": f"The {field.replace('_', ' ')} requirement is different.",
                })
        acd_warnings = acd[index].get("mandatory_warnings") or []
        singapore_warnings = singapore[index].get("mandatory_warnings") or []
        if bool(acd_warnings) != bool(singapore_warnings):
            differences.append({
                "aspect": "mandatory_warnings",
                "acd": _display(acd_warnings),
                "singapore": _display(singapore_warnings),
                "effect": "One source imposes a mandatory warning that the other does not record.",
            })
        elif acd_warnings != singapore_warnings:
            uncertain.append("mandatory warning wording")
        for field in ("product_category", "unstructured_conditions"):
            if acd[index].get(field) != singapore[index].get(field):
                uncertain.append(field.replace("_", " "))

    if differences:
        status = "material_difference"
        summary = "Singapore and ACD contain a confirmed difference in a regulatory requirement. Singapore screening uses the Singapore requirement."
        verification_needed = None
    elif uncertain:
        ai = reference.get("ai_semantic_interpretation") or {}
        if ai.get("outcome") == "equivalent" and ai.get("source_citations"):
            status = "equivalent"
            summary = "Singapore and ACD express the same regulatory requirement using different wording."
            verification_needed = None
        else:
            status = "verification_required"
            summary = "No confirmed regulatory conflict was identified, but wording-dependent applicability remains unresolved."
            verification_needed = "Verify whether " + " and ".join(sorted(set(uncertain))) + " describe the same regulatory scope."
    else:
        status = "equivalent"
        summary = "Singapore and ACD impose the same structured regulatory requirement."
        verification_needed = None

    return {
        **reference,
        "material_difference": status == "material_difference",
        "professional_review_required": status != "equivalent",
        "semantic_comparison_status": status,
        "confirmed_material_difference": status == "material_difference",
        "requirement_differences": differences,
        "comparison_summary": summary,
        "verification_needed": verification_needed,
        "comparison_method": "deterministic_semantic_validation" + ("_with_cached_ai_wording_review" if reference.get("ai_semantic_interpretation") else ""),
        "comparison_citations": citations,
    }


class RegulatoryComparisonService:
    """Cached semantic comparison with an optional structured AI wording pass.

    The interpreter receives only source-backed rule data and must return a
    structured interpretation. Its output can establish wording equivalence,
    but it cannot turn an unverified textual observation into a legal finding.
    """

    def __init__(self, interpreter: Callable[[dict[str, Any]], dict[str, Any]] | None = None):
        self.interpreter = interpreter
        self._cache: dict[str, dict[str, Any]] = {}

    def compare(
        self,
        reference: dict[str, Any],
        rules_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        relevant_rules = {
            rule_id: rules_by_id[rule_id]
            for rule_id in reference.get("acd_rule_ids", []) + reference.get("singapore_rule_ids", [])
            if rule_id in rules_by_id
        }
        cache_key = hashlib.sha256(json.dumps(
            {"reference": reference, "rules": relevant_rules},
            sort_keys=True,
            default=str,
        ).encode("utf-8")).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = validate_regulatory_comparison(reference, rules_by_id)
        if result["semantic_comparison_status"] == "verification_required" and self.interpreter:
            interpretation = self.interpreter({
                "cross_reference_id": reference.get("cross_reference_id"),
                "rules": relevant_rules,
                "required_output": {
                    "outcome": "equivalent | potentially_different",
                    "reasoning_dimensions": [
                        "concentration limits", "product categories", "permitted uses",
                        "exceptions", "mandatory warnings", "effective dates",
                    ],
                    "source_citations": "non-empty list of rule IDs and source pages",
                },
            })
            result = validate_regulatory_comparison(
                {**reference, "ai_semantic_interpretation": interpretation},
                rules_by_id,
            )
        self._cache[cache_key] = result
        return result

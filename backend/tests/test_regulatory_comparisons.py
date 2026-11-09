from __future__ import annotations

from copy import deepcopy

from data_pipeline.scripts.regulatory_semantics import (
    RegulatoryComparisonService,
    validate_regulatory_comparison,
)
from backend.app.services.loader import load_accepted_store


def _rule(rule_id: str, section: str, *, limit: float = 1.0, condition: str | None = None) -> dict:
    return {
        "rule_id": rule_id,
        "regulatory_section": section,
        "reference_number": "29",
        "case_label": None,
        "concentration": {
            "value": limit,
            "unit": "percent",
            "comparator": "less_than_or_equal",
            "preparation_stage": "finished_product",
            "source_text": f"Maximum {limit}%",
        },
        "permitted_function": "preservative",
        "product_context": None,
        "applicability_requirements": [],
        "combined_limit_requirements": [],
        "warning_requirements": [],
        "required_warning": None,
        "other_conditions": condition,
        "effective_date": None,
        "source_url": f"https://example.test/{rule_id}",
        "source_pages": [1],
    }


def _reference() -> dict:
    return {
        "cross_reference_id": "xref-test-29",
        "acd_rule_ids": ["acd"],
        "singapore_rule_ids": ["sg"],
        "comparison_status": "changed",
        "field_differences": {"concentration_text": {"acd": "1.0 %", "singapore": "1%"}},
    }


def test_equivalent_formatting_does_not_create_material_difference() -> None:
    rules = {"acd": _rule("acd", "Annex VI"), "sg": _rule("sg", "Third Schedule Part IV")}
    result = validate_regulatory_comparison(_reference(), rules)

    assert result["semantic_comparison_status"] == "equivalent"
    assert result["confirmed_material_difference"] is False
    assert result["requirement_differences"] == []


def test_genuine_limit_difference_is_reported_exactly() -> None:
    rules = {"acd": _rule("acd", "Annex VI", limit=0.8), "sg": _rule("sg", "Third Schedule Part IV", limit=1.0)}
    result = validate_regulatory_comparison(_reference(), rules)

    assert result["semantic_comparison_status"] == "material_difference"
    assert result["confirmed_material_difference"] is True
    difference = result["requirement_differences"][0]
    assert difference["aspect"] == "concentration_limit"
    assert '"value": 0.8' in difference["acd"]
    assert '"value": 1.0' in difference["singapore"]


def test_uncertain_wording_states_what_needs_verification() -> None:
    rules = {
        "acd": _rule("acd", "Annex VI", condition="Except for oral products"),
        "sg": _rule("sg", "Third Schedule Part IV", condition="Not for products used in the mouth"),
    }
    result = validate_regulatory_comparison(_reference(), rules)

    assert result["semantic_comparison_status"] == "verification_required"
    assert result["confirmed_material_difference"] is False
    assert "unstructured conditions" in result["verification_needed"]


def test_cached_ai_interpretation_can_confirm_equivalent_wording_only_once() -> None:
    calls: list[dict] = []
    service = RegulatoryComparisonService(lambda payload: calls.append(payload) or {
        "outcome": "equivalent",
        "reasoning_dimensions": ["exceptions"],
        "source_citations": ["acd page 1", "sg page 1"],
    })
    rules = {
        "acd": _rule("acd", "Annex VI", condition="Except for oral products"),
        "sg": _rule("sg", "Third Schedule Part IV", condition="Not for products used in the mouth"),
    }

    first = service.compare(_reference(), rules)
    second = service.compare(deepcopy(_reference()), deepcopy(rules))

    assert first["semantic_comparison_status"] == "equivalent"
    assert second == first
    assert len(calls) == 1


def test_phenoxyethanol_singapore_and_acd_both_have_one_percent_limit() -> None:
    store = load_accepted_store()
    reference = next(item for item in store.cross_references if item["cross_reference_id"] == "xref-annex-vi-to-third-schedule-part-iv-29")

    assert reference["semantic_comparison_status"] == "equivalent"
    assert reference["confirmed_material_difference"] is False
    assert reference["material_difference"] is False
    assert reference["professional_review_required"] is False
    assert reference["requirement_differences"] == []

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.models.screening import ConcentrationInput, Finding, IngredientInput, RegulatedFunction
from backend.app.services.compliance import screen_ingredient
from backend.app.services.loader import ALL_REGULATORY_SEARCH_SCOPE, load_accepted_store


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def store():
    return load_accepted_store(ROOT)


def concentration(value: float, *, unit: str = "percent", basis: str | None = None, stage: str = "finished_product"):
    return ConcentrationInput(value=value, unit=unit, basis=basis, preparation_stage=stage)


def positive_store(store, function: RegulatedFunction, **changes):
    base = store.rules_by_id["sg-third-schedule-ii-5"]
    section = {
        RegulatedFunction.COLOURANT: "Third Schedule Part III",
        RegulatedFunction.PRESERVATIVE: "Third Schedule Part IV",
        RegulatedFunction.UV_FILTER: "Third Schedule Part V",
    }[function]
    rule = {
        **base,
        "rule_id": f"synthetic-{function.value}",
        "regulatory_section": section,
        "reference_number": "TEST-1",
        "restriction_type": "permitted",
        "regulatory_category": function.value,
        "list_semantics": "positive_list",
        "permitted_function": function.value,
        "concentration": {
            "value": 0.2, "unit": "percent", "comparator": "less_than_or_equal",
            "basis": None, "preparation_stage": "finished_product", "source_text": "0.2%",
        },
        "other_conditions": "",
        "required_warning": "",
        "applicability_requirements": [],
        "combined_limit_requirements": [],
        "warning_requirements": [],
        "normalization_status": "normalized",
        "review_reasons": [],
        **changes,
    }
    substance_id = base["substance_id"]
    rules = tuple([base, rule])
    return replace(
        store,
        rules_by_id={**store.rules_by_id, rule["rule_id"]: rule},
        rules_by_substance_id={**store.rules_by_substance_id, substance_id: rules},
        singapore_rules_by_function={**store.singapore_rules_by_function, function.value: (rule,)},
        positive_list_functions=frozenset({*store.positive_list_functions, function.value}),
        regulatory_search_scope=ALL_REGULATORY_SEARCH_SCOPE,
    ), rule


@pytest.mark.parametrize("function", list(RegulatedFunction))
def test_positive_list_within_and_above_limit(store, function):
    synthetic, _ = positive_store(store, function)
    within = screen_ingredient(synthetic, IngredientInput(
        name="Tosylchloramide sodium", concentration=concentration(0.1), regulated_functions=[function],
    ))
    above = screen_ingredient(synthetic, IngredientInput(
        name="Tosylchloramide sodium", concentration=concentration(0.3), regulated_functions=[function],
    ))
    assert Finding.PERMITTED_USE_WITHIN_CONDITIONS in within.confirmed_findings
    assert above.primary_finding == Finding.PERMITTED_USE_CONDITION_NOT_MET


def test_colourant_product_condition_and_hair_colouring_exclusion(store):
    synthetic, _ = positive_store(store, RegulatedFunction.COLOURANT, applicability_requirements=[{
        "fact": "eye_area", "expected": False, "source_text": "Not for use near the eyes",
    }])
    failed = screen_ingredient(
        synthetic,
        IngredientInput(name="Tosylchloramide sodium", concentration=concentration(0.1), regulated_functions=[RegulatedFunction.COLOURANT]),
        product_applicability={"eye_area": True},
    )
    excluded = screen_ingredient(
        synthetic,
        IngredientInput(name="Tosylchloramide sodium", concentration=concentration(0.1), regulated_functions=[RegulatedFunction.COLOURANT]),
        product_applicability={"solely_hair_colouring": True},
    )
    assert failed.primary_finding == Finding.PERMITTED_USE_CONDITION_NOT_MET
    assert excluded.function_evaluations[0].status == "not_applicable"


def test_missing_applicability_fact_is_information_missing(store):
    synthetic, _ = positive_store(store, RegulatedFunction.PRESERVATIVE, applicability_requirements=[{
        "fact": "rinse_off", "expected": True, "source_text": "Rinse-off products only",
    }])
    result = screen_ingredient(
        synthetic,
        IngredientInput(name="Tosylchloramide sodium", concentration=concentration(0.1), regulated_functions=[RegulatedFunction.PRESERVATIVE]),
    )
    assert result.primary_finding == Finding.INFORMATION_MISSING
    assert result.condition_evaluations[0].status == "information_missing"


def test_confirmed_function_absent_from_complete_list_is_bounded_issue(store):
    synthetic, uv_rule = positive_store(store, RegulatedFunction.UV_FILTER)
    substance_id = uv_rule["substance_id"]
    synthetic = replace(
        synthetic,
        rules_by_substance_id={**synthetic.rules_by_substance_id, substance_id: (store.rules_by_id["sg-third-schedule-ii-5"],)},
    )
    result = screen_ingredient(
        synthetic,
        IngredientInput(name="Tosylchloramide sodium", concentration=concentration(0.1), regulated_functions=[RegulatedFunction.UV_FILTER]),
    )
    assert result.primary_finding == Finding.REGULATED_FUNCTION_NOT_PERMITTED


def test_unknown_function_never_creates_positive_list_prohibition(store):
    synthetic, _ = positive_store(store, RegulatedFunction.PRESERVATIVE)
    result = screen_ingredient(synthetic, IngredientInput(name="Tosylchloramide sodium", concentration=concentration(0.1)))
    assert result.primary_finding != Finding.REGULATED_FUNCTION_NOT_PERMITTED
    assert RegulatedFunction.PRESERVATIVE in result.incomplete_positive_list_checks


def test_multiple_functions_and_categories_are_all_retained(store):
    with_preservative, preservative = positive_store(store, RegulatedFunction.PRESERVATIVE)
    with_both, uv = positive_store(with_preservative, RegulatedFunction.UV_FILTER)
    substance_id = preservative["substance_id"]
    with_both = replace(
        with_both,
        rules_by_substance_id={**with_both.rules_by_substance_id, substance_id: (store.rules_by_id["sg-third-schedule-ii-5"], preservative, uv)},
    )
    result = screen_ingredient(with_both, IngredientInput(
        name="Tosylchloramide sodium", concentration=concentration(0.1),
        regulated_functions=[RegulatedFunction.PRESERVATIVE, RegulatedFunction.UV_FILTER],
    ))
    assert {item.regulated_function for item in result.function_evaluations} == {RegulatedFunction.PRESERVATIVE, RegulatedFunction.UV_FILTER}


def test_incompatible_concentration_semantics_and_combined_limits_require_review(store):
    synthetic, _ = positive_store(store, RegulatedFunction.PRESERVATIVE)
    incompatible = screen_ingredient(synthetic, IngredientInput(
        name="Tosylchloramide sodium", concentration=concentration(100, unit="ppm"),
        regulated_functions=[RegulatedFunction.PRESERVATIVE],
    ))
    combined_store, _ = positive_store(store, RegulatedFunction.PRESERVATIVE, combined_limit_requirements=[{
        "group_key": "parabens", "maximum": {"value": 0.8, "unit": "percent", "comparator": "less_than_or_equal", "basis": None, "preparation_stage": "finished_product", "source_text": "0.8%"},
        "constituent_references": ["12", "12a"], "source_text": "Combined maximum 0.8%",
    }])
    combined = screen_ingredient(combined_store, IngredientInput(
        name="Tosylchloramide sodium", concentration=concentration(0.1),
        regulated_functions=[RegulatedFunction.PRESERVATIVE],
    ))
    assert incompatible.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert combined.primary_finding == Finding.PROFESSIONAL_REVIEW


def test_numeric_limit_does_not_hide_unstructured_nano_conditions(store):
    nano_store, _ = positive_store(
        store,
        RegulatedFunction.UV_FILTER,
        other_conditions="Not for inhalation exposure; particle-form requirements also apply.",
    )
    result = screen_ingredient(
        nano_store,
        IngredientInput(
            name="Tosylchloramide sodium",
            concentration=concentration(0.1),
            regulated_functions=[RegulatedFunction.UV_FILTER],
        ),
    )
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.review_required is True
    assert result.rule_evaluations[-1].evaluation_status == "withheld_professional_review"


def test_warning_is_structured_without_claiming_label_satisfaction(store):
    synthetic, _ = positive_store(store, RegulatedFunction.UV_FILTER, warning_requirements=[{
        "warning_text": "Contains test filter", "trigger_text": "When used for sun protection", "applicability": "structured",
    }])
    result = screen_ingredient(synthetic, IngredientInput(
        name="Tosylchloramide sodium", concentration=concentration(0.1), regulated_functions=[RegulatedFunction.UV_FILTER],
    ))
    assert result.warning_requirements[0].warning_text == "Contains test filter"
    assert result.warning_requirements[0].applicability == "applicable"


def test_triggered_source_warning_stays_undetermined_until_review(store):
    synthetic, _ = positive_store(store, RegulatedFunction.UV_FILTER, warning_requirements=[{
        "warning_text": "Contains formaldehyde",
        "trigger_text": "When released formaldehyde exceeds 0.05%",
        "applicability": "professional_review",
    }])
    result = screen_ingredient(synthetic, IngredientInput(
        name="Tosylchloramide sodium",
        concentration=concentration(0.1),
        regulated_functions=[RegulatedFunction.UV_FILTER],
    ))
    assert result.warning_requirements[0].warning_text == "Contains formaldehyde"
    assert result.warning_requirements[0].applicability == "undetermined"


def test_material_acd_difference_requires_review_without_replacing_singapore_finding(store):
    synthetic, rule = positive_store(store, RegulatedFunction.PRESERVATIVE)
    xref = {"comparison_status": "changed", "material_difference": True, "acd_rule_ids": [], "singapore_rule_ids": [rule["rule_id"]]}
    synthetic = replace(synthetic, cross_references_by_rule_id={**synthetic.cross_references_by_rule_id, rule["rule_id"]: (xref,)})
    result = screen_ingredient(synthetic, IngredientInput(
        name="Tosylchloramide sodium", concentration=concentration(0.1), regulated_functions=[RegulatedFunction.PRESERVATIVE],
    ))
    assert Finding.PERMITTED_USE_WITHIN_CONDITIONS in result.confirmed_findings
    assert result.review_required is True
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW


def test_ci_identifier_resolves_to_colourant_rule_and_checks_limit(store):
    within = screen_ingredient(
        store,
        IngredientInput(
            name="CI 12085",
            concentration=concentration(2),
            regulated_functions=[RegulatedFunction.COLOURANT],
        ),
    )
    exceeded = screen_ingredient(
        store,
        IngredientInput(
            name="CI 12085",
            concentration=concentration(4),
            regulated_functions=[RegulatedFunction.COLOURANT],
        ),
    )

    assert within.identity.status == "resolved"
    assert "exact_ci" in within.identity.match_methods
    assert Finding.PERMITTED_USE_WITHIN_CONDITIONS in within.confirmed_findings
    assert [item.rule_id for item in within.rule_evaluations] == ["sg-third-schedule-iii-12085"]
    assert exceeded.primary_finding == Finding.PERMITTED_USE_CONDITION_NOT_MET


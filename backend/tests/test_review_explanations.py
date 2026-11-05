from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.config import OpenAISettings, load_settings
from backend.app.main import create_app
from backend.app.models.formulation import FormulationRequest
from backend.app.services.formulation import screen_formulation
from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.ingredient_linkage import load_accepted_ingredient_linkages
from backend.app.services.loader import load_accepted_store
from backend.app.services.review_explanations import ReviewExplanationService


ROOT = Path(__file__).resolve().parents[2]


def review_response():
    return screen_formulation(
        load_accepted_store(ROOT),
        FormulationRequest.model_validate({"ingredients": [{"name": "Mystery Extract"}]}),
        ingredient_catalog=load_accepted_ingredient_catalog(ROOT),
    )


class FakeResponses:
    def __init__(self, output: dict):
        self.output = output
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(self.output),
            model="gpt-5.6-luna-verified",
            usage=SimpleNamespace(input_tokens=120, output_tokens=35, total_tokens=155),
        )


def valid_output() -> dict:
    return {"explanations": [{
        "item_id": "1",
        "title": "Ingredient identity needs confirmation",
        "summary": "The ingredient name and CAS information do not clearly point to one source-backed ingredient.",
        "what_to_check": "Confirm the correct INCI or common name and CAS number.",
        "submitted_fact": None,
        "regulatory_fact": None,
    }]}


def test_model_explanation_is_batched_grounded_and_cached():
    fake = FakeResponses(valid_output())
    service = ReviewExplanationService("test-key", client_factory=lambda **_: SimpleNamespace(responses=fake))
    deterministic = review_response()
    deterministic.ingredient_results[0].review_issues = []
    original_finding = deterministic.ingredient_results[0].primary_finding
    first = service.enrich(deterministic)
    second = service.enrich(deterministic)
    assert len(fake.calls) == 1
    assert fake.calls[0]["store"] is False
    assert fake.calls[0]["tools"] == []
    assert "short sentences, simple words" in fake.calls[0]["instructions"]
    assert "conditional wording" in fake.calls[0]["instructions"]
    assert "raw_fragments" not in fake.calls[0]["input"][0]["content"]
    assert first.ingredient_results[0].primary_finding == original_finding
    assert first.ingredient_results[0].review_required is True
    assert first.ingredient_results[0].review_explanation.source == "model"
    assert first.review_explanation_metadata.actual_model == "gpt-5.6-luna-verified"
    assert first.review_explanation_metadata.usage.total_tokens == 155
    assert second.ingredient_results[0].review_explanation.source == "model"


def test_missing_key_keeps_review_and_uses_plain_fallback():
    deterministic = review_response()
    enriched = ReviewExplanationService(None).enrich(deterministic)
    result = enriched.ingredient_results[0]
    assert result.primary_finding == deterministic.ingredient_results[0].primary_finding
    assert result.review_required is True
    assert result.review_explanation.source == "deterministic_fallback"
    assert result.review_explanation.title == "Ingredient identity needs confirmation"
    assert enriched.review_explanation_metadata.status == "fallback"


def test_stage_and_conditional_fallbacks_are_plain_and_actionable():
    store = load_accepted_store(ROOT)
    catalogue = load_accepted_ingredient_catalog(ROOT)
    stage_response = screen_formulation(
        store,
        FormulationRequest.model_validate({"ingredients": [{
            "name": "Tosylchloramide sodium",
            "concentration": {"value": 0.1, "unit": "percent", "basis": None, "preparation_stage": "ready_for_use"},
        }]}),
        ingredient_catalog=catalogue,
    )
    stage_result = ReviewExplanationService(None).enrich(stage_response).ingredient_results[0]
    assert stage_result.review_explanation.title == "Concentration stage needs confirmation"
    assert stage_result.review_explanation.summary == (
        "The submitted concentration is for one stage, but the rule applies at a different stage."
    )
    assert stage_result.review_explanation.what_to_check == "Confirm the concentration at the stage stated in the rule."

    conditional_response = screen_formulation(
        store,
        FormulationRequest.model_validate({"ingredients": [{"name": "DIETHYLENE GLYCOL"}]}),
        ingredient_catalog=catalogue,
    )
    conditional_result = ReviewExplanationService(None).enrich(conditional_response).ingredient_results[0]
    assert conditional_result.review_required is True
    assert conditional_result.review_explanation.title == "Rule exception needs confirmation"
    assert conditional_result.review_explanation.summary == "This rule has an exception that still needs checking."
    assert conditional_result.review_explanation.what_to_check.startswith("Check whether the exception")


def test_name_and_cas_conflict_has_specific_plain_fallback_and_grounded_facts():
    deterministic = screen_formulation(
        load_accepted_store(ROOT),
        FormulationRequest.model_validate({"ingredients": [{
            "name": "Aminophylline",
            "cas_number": "58-55-9",
        }]}),
        ingredient_catalog=load_accepted_ingredient_catalog(ROOT),
    )
    result = ReviewExplanationService(None).enrich(deterministic).ingredient_results[0]
    explanation = result.review_explanation
    assert result.review_required is True
    assert explanation.title == "Name and CAS do not match"
    assert explanation.summary == "The submitted name and CAS number match different source-backed ingredient identities."
    assert explanation.what_to_check == "Confirm the correct ingredient name and CAS number."
    assert explanation.submitted_fact == "Name: Aminophylline · CAS: 58-55-9"
    assert explanation.regulatory_fact == "Source CAS for Aminophylline: 317-34-0"


def test_recognised_cas_with_unlinked_catalogue_name_is_not_called_a_conflict():
    deterministic = screen_formulation(
        load_accepted_store(ROOT),
        FormulationRequest.model_validate({"ingredients": [{
            "name": "PHENOXYETHANOL",
            "cas_number": "122-99-6",
            "regulated_functions": ["preservative"],
            "concentration": {"value": 0.5, "unit": "percent", "basis": None, "preparation_stage": "finished_product"},
        }]}),
        ingredient_catalog=load_accepted_ingredient_catalog(ROOT),
    )
    result = ReviewExplanationService(None).enrich(deterministic).ingredient_results[0]
    assert result.identity.identity_outcome.value == "cas_recognised_name_unverified"
    assert result.rule_evaluations
    assert result.review_explanation.title == "Ingredient name needs confirmation"
    assert "do not match" not in result.review_explanation.summary


def test_model_jargon_is_rejected_and_plain_fallback_is_kept():
    jargon = valid_output()
    jargon["explanations"][0]["title"] = "Conditional wording needs review"
    jargon["explanations"][0]["summary"] = "The cited entry could not be structured automatically."
    fake = FakeResponses(jargon)
    enriched = ReviewExplanationService(
        "test-key", client_factory=lambda **_: SimpleNamespace(responses=fake)
    ).enrich(review_response())
    explanation = enriched.ingredient_results[0].review_explanation
    assert explanation.source == "deterministic_fallback"
    assert "cited entry" not in explanation.summary.casefold()


def test_unsafe_or_ungrounded_model_output_fails_closed():
    unsafe = valid_output()
    unsafe["explanations"][0]["summary"] = "This ingredient is approved and safe at 99%."
    fake = FakeResponses(unsafe)
    service = ReviewExplanationService("test-key", client_factory=lambda **_: SimpleNamespace(responses=fake))
    enriched = service.enrich(review_response())
    assert enriched.ingredient_results[0].review_explanation.source == "deterministic_fallback"
    assert enriched.review_explanation_metadata.model_count == 0
    assert enriched.review_explanation_metadata.fallback_count == 1


def test_non_review_results_do_not_call_explanation_model():
    deterministic = screen_formulation(
        load_accepted_store(ROOT),
        FormulationRequest.model_validate({"ingredients": [{"name": "NIACINAMIDE"}]}),
        ingredient_catalog=load_accepted_ingredient_catalog(ROOT),
    )
    fake = FakeResponses({"explanations": []})
    enriched = ReviewExplanationService("test-key", client_factory=lambda **_: SimpleNamespace(responses=fake)).enrich(deterministic)
    assert fake.calls == []
    assert enriched.ingredient_results[0].review_explanation is None
    assert enriched.review_explanation_metadata.status == "not_needed"


def test_structured_combined_limit_explanation_names_missing_constituent_and_limits():
    deterministic = screen_formulation(
        load_accepted_store(ROOT),
        FormulationRequest.model_validate({
            "product_applicability": {"inhalation_exposure": False},
            "ingredients": [{
                "name": "Zinc oxide",
                "regulated_functions": ["uv_filter"],
                "concentration": {
                    "concentration_type": "approximate",
                    "value": 2,
                    "unit": "percent",
                    "basis": None,
                    "preparation_stage": "finished_product",
                    "original_text": "approximately 2%",
                },
            }],
        }),
        ingredient_catalog=load_accepted_ingredient_catalog(ROOT),
        linkage_store=load_accepted_ingredient_linkages(ROOT),
    )
    enriched = ReviewExplanationService(None).enrich(deterministic)
    explanation = enriched.ingredient_results[0].review_explanation
    combined = next(item for item in explanation.items if item.issue_code == "combined_limit_information_missing")
    assert "Zinc oxide (nano)" in combined.what_happened
    assert "approximately 2%" in combined.why_it_matters
    assert "25 percent" in combined.why_it_matters
    assert "combined concentration" in combined.what_to_check
    assert explanation.reviewer_actions == list(dict.fromkeys(explanation.reviewer_actions))
    assert explanation.primary_source_references


def test_octocrylene_branches_share_one_product_type_action_and_show_both_limits():
    deterministic = screen_formulation(
        load_accepted_store(ROOT),
        FormulationRequest.model_validate({
            "ingredients": [{
                "name": "Octocrylene",
                "cas_number": "6197-30-4",
                "regulated_functions": ["uv_filter"],
                "concentration": {
                    "concentration_type": "range",
                    "lower_bound": 8,
                    "upper_bound": 12,
                    "lower_inclusive": True,
                    "upper_inclusive": True,
                    "unit": "percent",
                    "basis": None,
                    "preparation_stage": "finished_product",
                    "original_text": "8–12%",
                },
            }],
        }),
        ingredient_catalog=load_accepted_ingredient_catalog(ROOT),
        linkage_store=load_accepted_ingredient_linkages(ROOT),
    )
    result = ReviewExplanationService(None).enrich(deterministic).ingredient_results[0]
    explanation = result.review_explanation

    product_type_actions = [
        action for action in explanation.reviewer_actions
        if "spray or aerosol" in action.casefold()
    ]
    assert len(product_type_actions) == 1
    assert "9%" in explanation.regulatory_fact
    assert "10%" in explanation.regulatory_fact
    assert len(explanation.reviewer_actions) == len({action.casefold().rstrip(".") for action in explanation.reviewer_actions})


def test_screening_route_returns_inline_fallback_without_changing_result():
    store = load_accepted_store(ROOT)
    catalogue = load_accepted_ingredient_catalog(ROOT)
    with TestClient(create_app(
        lambda: store,
        lambda: catalogue,
        settings_loader=lambda: OpenAISettings(None, "gpt-5.6-sol", "gpt-5.6-luna"),
    )) as client:
        response = client.post("/screen-formulation", json={"ingredients": [{"name": "Mystery Extract"}]})
    assert response.status_code == 200
    payload = response.json()
    result = payload["ingredient_results"][0]
    assert result["primary_finding"] == "identity_unresolved"
    assert result["review_required"] is True
    assert result["review_explanation"]["source"] == "deterministic_fallback"
    assert payload["review_explanation_metadata"]["status"] == "fallback"


@pytest.mark.openai_integration
@pytest.mark.skipif(os.getenv("RUN_OPENAI_INTEGRATION") != "1", reason="live OpenAI checks are explicitly opt-in")
def test_live_explanation_is_optional():
    settings = load_settings()
    if not settings.api_key:
        pytest.skip("OPENAI_API_KEY is not configured")
    enriched = ReviewExplanationService(settings.api_key, settings.explanation_model).enrich(review_response())
    metadata = enriched.review_explanation_metadata
    assert metadata.status == "model"
    assert metadata.actual_model and metadata.actual_model.startswith(settings.explanation_model)
    assert enriched.ingredient_results[0].review_explanation.source == "model"
    print(json.dumps({
        "model": metadata.actual_model,
        "input_tokens": metadata.usage.input_tokens,
        "output_tokens": metadata.usage.output_tokens,
        "total_tokens": metadata.usage.total_tokens,
    }))

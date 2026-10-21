from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.models.screening import ConcentrationInput, Finding, IdentityStatus, IngredientInput
from backend.app.models.screening import SingaporeLinkageStatus
from backend.app.services.compliance import screen_ingredient
from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.loader import ALL_REGULATORY_SEARCH_SCOPE, AcceptedBaselineError, load_accepted_store
from backend.app.services.regulatory_search import search_acd_rules
from backend.app.services.resolver import resolve_ingredient
from backend.app.services.review_pack import build_review_pack
from backend.app.services.search_names import derived_except_search_name


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def store():
    return load_accepted_store(ROOT)


@pytest.fixture(scope="session")
def ingredient_catalog():
    return load_accepted_ingredient_catalog(ROOT)


def test_catalogue_exact_search_is_case_insensitive_and_not_fuzzy(ingredient_catalog):
    assert ingredient_catalog.find_exact_name(" niacinamide ")["canonical_name"] == "NIACINAMIDE"
    assert ingredient_catalog.find_exact_name("niacinamid") is None
    assert ingredient_catalog.search("nia", limit=2)[0]["canonical_name"].startswith("NIA")
    assert len(ingredient_catalog.search("a", limit=20)) == 20


def test_catalogue_identity_without_scoped_listing_is_bounded_no_issue(store, ingredient_catalog):
    result = screen_ingredient(store, IngredientInput(name="Niacinamide"), ingredient_catalog=ingredient_catalog)
    assert result.primary_finding == Finding.NO_ISSUE
    assert result.identity.status == IdentityStatus.RESOLVED
    assert result.identity.catalogue_identity.canonical_name == "NIACINAMIDE"
    assert result.identity.singapore_linkage_status == SingaporeLinkageStatus.NOT_APPLICABLE
    assert result.identity.linkage_evidence is None
    assert result.review_required is False
    assert result.searched_regulatory_sections == list(ALL_REGULATORY_SEARCH_SCOPE)
    assert "No matching entry was identified" in result.scope_note
    assert "overall product compliance" in result.scope_note


def test_literal_except_alias_finds_conditional_regulatory_record(store, ingredient_catalog):
    result = screen_ingredient(
        store,
        IngredientInput(name="Diethylene glycol"),
        ingredient_catalog=ingredient_catalog,
    )
    assert result.identity.identity_source_type.value == "singapore_regulatory_source"
    assert "derived_source_name_except_clause" in result.identity.match_methods
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert {item.rule_id for item in result.rule_evaluations} == {"sg-third-schedule-i-a1140"}
    assert "except if it is present" in result.rule_evaluations[0].evidence.substance_name


def test_literal_except_alias_helper_does_not_strip_other_parentheses():
    assert derived_except_search_name("Diethylene glycol (except if present)") == "Diethylene glycol"
    assert derived_except_search_name("Diethylene glycol (DEG)") is None
    assert derived_except_search_name("2-(ethoxyethoxy)-ethanol") is None


def test_multiple_derived_alias_matches_remain_ambiguous(store):
    synthetic = replace(
        store,
        substances_by_derived_search_name={
            **store.substances_by_derived_search_name,
            "synthetic conditional name": (
                store.substances_by_id["substance-sg-third-schedule-i-a1136"],
                store.substances_by_id["substance-sg-third-schedule-i-a1137"],
            ),
        },
    )
    result = resolve_ingredient(synthetic, "Synthetic conditional name", None)
    assert result.status == IdentityStatus.AMBIGUOUS
    assert len(result.singapore_candidates) == 2
    assert result.reasons == ["identifier_matches_multiple_singapore_identities"]


def test_acd_search_is_ranked_bounded_and_read_only(store):
    before = store.rules_by_id["acd-iii-14"].copy()
    results = search_acd_rules(store, "hydroquinone", limit=2)
    assert len(results) == 2
    assert results[0]["substance_name"].casefold().startswith("hydroquinone")
    assert all(item["regulatory_section"] in {"Annex II Part 1", "Annex III Part 1"} for item in results)
    assert store.rules_by_id["acd-iii-14"] == before


def concentration(value: float, *, unit: str = "percent", basis=None, stage="finished_product"):
    return ConcentrationInput(value=value, unit=unit, basis=basis, preparation_stage=stage)


def test_exact_singapore_name_resolution(store):
    result = resolve_ingredient(store, "Aminophylline", None)
    assert result.status == IdentityStatus.RESOLVED
    assert result.resolved_singapore_substance_id == "substance-sg-third-schedule-i-a1136"
    assert store.singapore_rules_by_schedule_reference[("Third Schedule Part I", "a1136")][0]["rule_id"] == "sg-third-schedule-i-a1136"
    assert store.rules_by_raw_record_id[store.rules_by_id["sg-third-schedule-i-a1136"]["raw_record_id"]]


def test_cas_resolution_through_aligned_cross_reference(store):
    result = resolve_ingredient(store, None, "317-34-0")
    assert result.status == IdentityStatus.RESOLVED
    assert result.match_methods == ["exact_cas_via_acd"]


def test_matching_name_and_cas_resolve_same_identity(store):
    result = resolve_ingredient(store, "Aminophylline", "317-34-0")
    assert result.status == IdentityStatus.RESOLVED
    assert result.resolved_singapore_substance_id == "substance-sg-third-schedule-i-a1136"


def test_matching_name_and_cas_can_corroborate_identity_despite_nonidentity_acd_difference(store):
    result = resolve_ingredient(store, "Glycyclamide", "664-95-9")
    assert result.status == IdentityStatus.RESOLVED
    assert result.resolved_singapore_substance_id == "substance-sg-third-schedule-i-100"


def test_name_and_cas_resolving_differently_are_ambiguous(store):
    result = resolve_ingredient(store, "Aminophylline", "58-55-9")
    assert result.status == IdentityStatus.AMBIGUOUS
    assert {candidate.reference_number for candidate in result.singapore_candidates} == {"A1136", "A1137"}


def test_one_of_two_identifiers_resolving_requires_review(store):
    result = resolve_ingredient(store, "Aminophylline", "7732-18-5")
    assert result.status == IdentityStatus.REVIEW_REQUIRED
    assert result.resolved_singapore_substance_id is None


def test_unresolved_identity_short_circuits_before_lookup(store):
    result = screen_ingredient(store, IngredientInput(name="Definitely absent ingredient"))
    assert result.primary_finding == Finding.IDENTITY_UNRESOLVED
    assert result.searched_singapore_parts == []
    assert result.rule_evaluations == []
    assert result.review_required is True


def test_duplicate_pentachloroethane_entries_resolve_to_one_identity_group(store):
    result = screen_ingredient(store, IngredientInput(name="Pentachloroethane"))
    assert result.primary_finding == Finding.PROHIBITED
    assert result.identity.status == IdentityStatus.RESOLVED
    assert len(result.identity.singapore_candidates) == 2
    assert set(result.identity.resolved_singapore_substance_ids) == {
        "substance-sg-third-schedule-i-264",
        "substance-sg-third-schedule-i-1170",
    }


def test_aminophylline_is_deterministically_prohibited(store):
    result = screen_ingredient(store, IngredientInput(name="Aminophylline"))
    assert result.primary_finding == Finding.PROHIBITED
    assert result.confirmed_findings == [Finding.PROHIBITED]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.2, Finding.WITHIN_LIMIT), (0.2001, Finding.RESTRICTION_EXCEEDED)],
)
def test_tosylchloramide_limit(store, value, expected):
    ingredient = IngredientInput(name="Tosylchloramide sodium", concentration=concentration(value))
    result = screen_ingredient(store, ingredient)
    assert result.primary_finding == expected


def test_no_product_context_required_when_no_matched_rule_needs_it(store):
    synthetic = replace(
        store,
        rules_by_substance_id={**store.rules_by_substance_id, "substance-sg-third-schedule-i-a1136": ()},
    )
    result = screen_ingredient(synthetic, IngredientInput(name="Aminophylline"))
    assert result.primary_finding == Finding.NO_ISSUE
    assert result.searched_singapore_parts == [
        "Third Schedule Part I",
        "Third Schedule Part II",
        "Third Schedule Part III",
        "Third Schedule Part IV",
        "Third Schedule Part V",
    ]


def test_missing_context_for_context_specific_rule(store):
    ingredient = IngredientInput(name="Chlorates of alkali metals", concentration=concentration(1))
    result = screen_ingredient(store, ingredient)
    assert result.primary_finding == Finding.INFORMATION_MISSING
    assert result.review_required is False
    assert any(
        "product context is required" in reason
        for evaluation in result.rule_evaluations
        for reason in evaluation.reasons
    )


def test_exact_source_backed_context_selects_chlorate_case(store):
    ingredient = IngredientInput(name="Chlorates of alkali metals", concentration=concentration(4))
    result = screen_ingredient(store, ingredient, product_context="Toothpaste")
    assert result.primary_finding == Finding.WITHIN_LIMIT
    assert [item.evaluation_status for item in result.rule_evaluations] == [
        "deterministic",
        "not_applicable_to_submitted_context",
    ]


def test_required_warning_is_returned_as_evidence(store):
    rule = store.rules_by_id["sg-third-schedule-ii-1a-case-a"]
    result = screen_ingredient(
        store,
        IngredientInput(name=rule["substance_name"], concentration=concentration(1)),
        product_context="Talc",
    )
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.confirmed_findings == [Finding.WITHIN_LIMIT]
    assert result.review_required is True
    assert result.rule_evaluations[0].evidence.required_warning == rule["required_warning"]

    exceeded = screen_ingredient(
        store,
        IngredientInput(name=rule["substance_name"], concentration=concentration(6)),
        product_context="Talc",
    )
    assert exceeded.primary_finding == Finding.RESTRICTION_EXCEEDED
    assert exceeded.review_required is True


def test_direct_singapore_name_is_not_downgraded_by_changed_acd_wording(store):
    result = resolve_ingredient(store, "Tranexamic acid", None)
    assert result.status == IdentityStatus.RESOLVED
    assert result.resolved_singapore_substance_id == "substance-sg-third-schedule-ii-a10"


def test_manual_multicase_rule_cannot_be_dismissed_by_context_mismatch(store):
    result = screen_ingredient(
        store,
        IngredientInput(name="Thioglycolic acid and its salts", concentration=concentration(0)),
        product_context="Talc",
    )
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.review_required is True
    assert any(item.evaluation_status == "withheld_professional_review" for item in result.rule_evaluations)


def test_blank_context_is_treated_as_missing(store):
    result = screen_ingredient(
        store,
        IngredientInput(name="Chlorates of alkali metals", concentration=concentration(1)),
        product_context="   ",
    )
    assert result.primary_finding == Finding.INFORMATION_MISSING


@pytest.mark.parametrize(
    "payload",
    [
        {"value": float("inf"), "unit": "percent", "basis": None, "preparation_stage": "finished_product"},
        {"value": 1, "unit": " ", "basis": None, "preparation_stage": "finished_product"},
        {"value": 1, "unit": "percent", "basis": " ", "preparation_stage": "finished_product"},
        {"value": 1, "unit": "percent", "basis": None, "preparation_stage": " "},
    ],
)
def test_invalid_concentration_semantics_are_rejected(payload):
    with pytest.raises(ValidationError):
        ConcentrationInput(**payload)


@pytest.mark.parametrize(
    "submitted",
    [concentration(0.1, unit="mg/kg"), concentration(0.1, basis="ingredient"), concentration(0.1, stage="raw_material")],
)
def test_incompatible_concentration_semantics_are_not_converted(store, submitted):
    result = screen_ingredient(
        store, IngredientInput(name="Tosylchloramide sodium", concentration=submitted)
    )
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.confirmed_findings == []


def test_missing_concentration_is_information_missing(store):
    result = screen_ingredient(store, IngredientInput(name="Tosylchloramide sodium"))
    assert result.primary_finding == Finding.INFORMATION_MISSING


def test_a1140_remains_non_executable(store):
    name = store.substances_by_id["substance-sg-third-schedule-i-a1140"]["original_substance_name"]
    result = screen_ingredient(store, IngredientInput(name=name))
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.confirmed_findings == []
    assert result.rule_evaluations[0].evaluation_status == "withheld_professional_review"


def test_unspecified_source_stage_is_not_executed_as_ingredient_concentration(store):
    result = screen_ingredient(
        store,
        IngredientInput(
            name="Peanut oil extracts and derivatives",
            concentration=concentration(0.6, unit="ppm", stage="unspecified"),
        ),
    )
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.confirmed_findings == []
    assert result.rule_evaluations[0].evaluation_status == "withheld_professional_review"
    assert "source preparation stage is not sufficiently specified" in result.rule_evaluations[0].reasons[0]


def _first_inactive_rule(store):
    return next(
        rule for rule in store.rules_by_id.values()
        if not rule["active"]
    )


def test_inactive_rule_is_evidence_only_and_does_not_block_no_issue(store):
    inactive = {
        **_first_inactive_rule(store),
        "substance_id": "substance-sg-third-schedule-i-a1136",
        "regulatory_section": "Third Schedule Part I",
    }
    synthetic = replace(
        store,
        rules_by_substance_id={**store.rules_by_substance_id, inactive["substance_id"]: (inactive,)},
    )
    result = screen_ingredient(synthetic, IngredientInput(name="Aminophylline"))
    assert result.primary_finding == Finding.NO_ISSUE
    assert len(result.inactive_evidence) == 1
    assert result.review_required is False


def test_unresolved_current_inactive_rule_blocks_no_issue(store):
    inactive = {
        **_first_inactive_rule(store),
        "substance_id": "substance-sg-third-schedule-i-a1136",
        "regulatory_section": "Third Schedule Part I",
        "unresolved_current_applicability": True,
    }
    synthetic = replace(
        store,
        rules_by_substance_id={**store.rules_by_substance_id, inactive["substance_id"]: (inactive,)},
    )
    result = screen_ingredient(synthetic, IngredientInput(name="Aminophylline"))
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.review_required is True


def test_confirmed_prohibition_survives_separate_review_flag(store):
    confirmed = store.rules_by_id["sg-third-schedule-i-a1136"]
    manual = {
        **store.rules_by_id["sg-third-schedule-i-a1140"],
        "substance_id": confirmed["substance_id"],
    }
    synthetic = replace(
        store,
        rules_by_substance_id={**store.rules_by_substance_id, confirmed["substance_id"]: (confirmed, manual)},
    )
    result = screen_ingredient(synthetic, IngredientInput(name="Aminophylline"))
    assert result.primary_finding == Finding.PROHIBITED
    assert result.review_required is True
    assert Finding.PROHIBITED in result.confirmed_findings


def test_confirmed_exceeded_survives_separate_review_flag(store):
    confirmed = store.rules_by_id["sg-third-schedule-ii-5"]
    manual = {
        **store.rules_by_id["sg-third-schedule-i-a1140"],
        "substance_id": confirmed["substance_id"],
    }
    synthetic = replace(
        store,
        rules_by_substance_id={**store.rules_by_substance_id, confirmed["substance_id"]: (confirmed, manual)},
    )
    result = screen_ingredient(
        synthetic,
        IngredientInput(name="Tosylchloramide sodium", concentration=concentration(0.3)),
    )
    assert result.primary_finding == Finding.RESTRICTION_EXCEEDED
    assert result.review_required is True


def test_source_evidence_is_complete(store):
    result = screen_ingredient(store, IngredientInput(name="Aminophylline"))
    evidence = result.rule_evaluations[0].evidence
    assert evidence.source_text == "A1136 | Aminophylline"
    assert evidence.source_pages == [13]
    assert evidence.source_url.startswith("https://sso.agc.gov.sg/")
    assert {item["paragraph"] for item in evidence.regulation_6_provisions} == {"1", "7"}
    assert evidence.raw_record_id
    assert evidence.raw_fragments[0]["row_bbox"]
    assert evidence.cross_references[0]["comparison_status"] == "aligned"
    assert evidence.dataset_version == store.dataset_version
    assert evidence.regulation_6_provisions[0]["source_url"].startswith("https://sso.agc.gov.sg/")
    assert evidence.acd_counterpart_rules[0]["raw_fragments"][0]["row_bbox"]
    assert result.accepted_baseline_sha256 == store.baseline_manifest_hash


def test_acd_only_bht_requires_professional_review(store):
    result = screen_ingredient(
        store, IngredientInput(name="Butylated Hydroxytoluene", cas_number="128-37-0")
    )
    assert result.primary_finding == Finding.PROFESSIONAL_REVIEW
    assert result.identity.resolved_singapore_substance_id is None


def test_loader_rejects_modified_baseline_file(store, tmp_path):
    (tmp_path / "data_pipeline" / "reports").mkdir(parents=True)
    shutil.copy(ROOT / "data_pipeline" / "accepted_output_hashes.json", tmp_path / "data_pipeline")
    shutil.copy(
        ROOT / "data_pipeline" / "reports" / "manual_spot_check_results.json",
        tmp_path / "data_pipeline" / "reports",
    )
    baseline = json.loads((ROOT / "data_pipeline" / "accepted_output_hashes.json").read_text(encoding="utf-8"))
    for relative_path in baseline["generated_output_hashes"]:
        source = ROOT / relative_path
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, destination)
    modified = tmp_path / "data_pipeline" / "processed" / "rules.json"
    modified.write_bytes(modified.read_bytes() + b" ")
    with pytest.raises(AcceptedBaselineError, match="hash mismatch"):
        load_accepted_store(tmp_path)


def test_review_pack_has_exactly_five_cases_per_category(store):
    pack = build_review_pack(store)
    assert pack["summary"]["total_cases"] == 25
    assert set(pack["summary"]["counts_by_category"].values()) == {5}
    assert len({item["case_id"] for item in pack["cases"]}) == 25


def test_runtime_loading_does_not_change_accepted_hashes():
    baseline = json.loads((ROOT / "data_pipeline" / "accepted_output_hashes.json").read_text(encoding="utf-8"))
    before = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in baseline["generated_output_hashes"]
    }
    load_accepted_store(ROOT)
    after = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in baseline["generated_output_hashes"]
    }
    assert after == before == baseline["generated_output_hashes"]

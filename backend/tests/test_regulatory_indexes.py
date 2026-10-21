from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.models.screening import Finding, IngredientInput
from backend.app.services.compliance import screen_ingredient
from backend.app.services.loader import ACD_SECTIONS, SINGAPORE_SECTIONS, load_accepted_store
from backend.app.services.resolver import resolve_ingredient
from data_pipeline.scripts.normalize import cas_is_valid, conservative_text


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def store():
    return load_accepted_store(ROOT)


def test_every_rule_and_cross_reference_has_complete_reverse_indexes(store):
    for rule_id, rule in store.rules_by_id.items():
        substance_id = rule.get("substance_id")
        assert rule["raw_record_id"] in store.raw_by_id, rule_id
        assert rule in store.rules_by_raw_record_id[rule["raw_record_id"]], rule_id
        if substance_id:
            assert substance_id in store.substances_by_id, rule_id
            assert rule in store.rules_by_substance_id[substance_id], rule_id
        if (
            rule["regulatory_section"] in SINGAPORE_SECTIONS
            and rule["active"]
            and rule["normalization_status"] == "normalized"
        ):
            assert rule in store.executable_singapore_rules_by_substance_id[substance_id], rule_id
        if rule["regulatory_section"] in SINGAPORE_SECTIONS:
            reference_key = rule["reference_number"].casefold()
            assert rule in store.singapore_rules_by_reference[reference_key], rule_id
            assert rule in store.singapore_rules_by_schedule_reference[
                (rule["regulatory_section"], reference_key)
            ], rule_id
            if rule.get("permitted_function"):
                assert rule in store.singapore_rules_by_function[rule["permitted_function"]], rule_id

    for cross_reference in store.cross_references:
        assert cross_reference["acd_rule_ids"] or cross_reference["singapore_rule_ids"]
        if not cross_reference["acd_rule_ids"]:
            assert cross_reference["comparison_status"] == "singapore_only"
        if not cross_reference["singapore_rule_ids"]:
            assert cross_reference["comparison_status"] in {"acd_only", "ambiguous"}
        for rule_id in cross_reference["acd_rule_ids"] + cross_reference["singapore_rule_ids"]:
            assert rule_id in store.rules_by_id, cross_reference["cross_reference_id"]
            assert cross_reference in store.cross_references_by_rule_id[rule_id]
        assert all(
            store.rules_by_id[rule_id]["regulatory_section"] in ACD_SECTIONS
            for rule_id in cross_reference["acd_rule_ids"]
        )
        assert all(
            store.rules_by_id[rule_id]["regulatory_section"] in SINGAPORE_SECTIONS
            for rule_id in cross_reference["singapore_rule_ids"]
        )


def test_every_active_identity_is_present_in_name_cas_and_ci_indexes(store):
    for substance_id, substance in store.substances_by_id.items():
        if not substance["active"]:
            continue
        name_matches = store.substances_by_name[substance["normalized_substance_name"]]
        assert substance_id in {item["substance_id"] for item in name_matches}
        for cas_number in substance["cas_numbers"]:
            if cas_is_valid(cas_number):
                assert substance_id in {
                    item["substance_id"] for item in store.substances_by_cas[cas_number]
                }

    for rule_id, rule in store.rules_by_id.items():
        substance_id = rule.get("substance_id")
        if not substance_id or not store.substances_by_id[substance_id]["active"]:
            continue
        for ci_identifier in (rule.get("regulatory_identifiers") or {}).get("ci", []):
            matches = store.substances_by_ci[conservative_text(str(ci_identifier))]
            assert substance_id in {item["substance_id"] for item in matches}, rule_id


def test_every_singapore_exact_name_round_trips_without_losing_rules(store):
    for name_key, substances in store.substances_by_name.items():
        expected_ids = {
            item["substance_id"]
            for item in substances
            if item["regulatory_section"] in SINGAPORE_SECTIONS
        }
        if not expected_ids:
            continue
        result = resolve_ingredient(store, substances[0]["original_substance_name"], None)
        candidate_ids = {item.substance_id for item in result.singapore_candidates}
        assert expected_ids <= candidate_ids, name_key


def test_every_cas_bridge_round_trips_to_all_linked_singapore_candidates(store):
    for cas_number, substances in store.substances_by_cas.items():
        expected_ids: set[str] = set()
        for substance in substances:
            for rule in store.rules_by_substance_id.get(substance["substance_id"], ()):
                for cross_reference in store.cross_references_by_rule_id.get(rule["rule_id"], ()):
                    for singapore_rule_id in cross_reference["singapore_rule_ids"]:
                        singapore_id = store.rules_by_id[singapore_rule_id].get("substance_id")
                        if singapore_id:
                            expected_ids.add(singapore_id)
        result = resolve_ingredient(store, None, cas_number)
        candidate_ids = {item.substance_id for item in result.singapore_candidates}
        assert expected_ids <= candidate_ids, cas_number


def test_every_ci_identifier_round_trips_to_its_singapore_colourant(store):
    for ci_identifier, substances in store.substances_by_ci.items():
        expected_ids = {
            item["substance_id"]
            for item in substances
            if item["regulatory_section"] == "Third Schedule Part III"
        }
        result = resolve_ingredient(store, f"CI {ci_identifier}", None)
        candidate_ids = {item.substance_id for item in result.singapore_candidates}
        resolved_ids = set(result.resolved_singapore_substance_ids)
        assert expected_ids <= candidate_ids
        assert expected_ids <= resolved_ids
        assert "exact_ci" in result.match_methods


def test_duplicate_source_entries_for_same_exact_identity_are_kept_together(store):
    result = screen_ingredient(store, IngredientInput(name="Pentachloroethane"))

    assert result.identity.status == "resolved"
    assert set(result.identity.resolved_singapore_substance_ids) == {
        "substance-sg-third-schedule-i-264",
        "substance-sg-third-schedule-i-1170",
    }
    assert result.primary_finding == Finding.PROHIBITED
    assert {item.rule_id for item in result.rule_evaluations} == {
        "sg-third-schedule-i-264",
        "sg-third-schedule-i-1170",
    }

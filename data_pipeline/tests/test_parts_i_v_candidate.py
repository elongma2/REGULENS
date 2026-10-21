from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from data_pipeline.scripts import candidate_pipeline
from data_pipeline.scripts.candidate_pipeline import validate_candidate
from data_pipeline.scripts.config import CANDIDATE_DATASET_VERSION


ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_candidate_contains_all_parts_and_annexes_without_changing_accepted_baseline():
    accepted_path = ROOT / "data_pipeline" / "accepted_output_hashes.json"
    before = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
    report = validate_candidate()
    after = hashlib.sha256(accepted_path.read_bytes()).hexdigest()

    assert report["validation_status"] == "passed"
    assert report["promotion_status"] == "promoted"
    assert before == after
    assert set(report["counts"]["raw_records_by_section"]) >= {
        "Annex IV Part 1", "Annex VI", "Annex VII",
        "Third Schedule Part III", "Third Schedule Part IV", "Third Schedule Part V",
    }
    assert all(report["counts"]["raw_records_by_section"][name] > 0 for name in (
        "Annex IV Part 1", "Annex VI", "Annex VII",
        "Third Schedule Part III", "Third Schedule Part IV", "Third Schedule Part V",
    ))


def test_candidate_preserves_versions_preambles_and_regulation_6_semantics():
    rules = _load(ROOT / "data_pipeline" / "candidate" / "processed" / "rules.json")
    provisions = _load(ROOT / "data_pipeline" / "candidate" / "processed" / "singapore_provisions.json")
    annex_vii = _load(ROOT / "data_pipeline" / "candidate" / "raw" / "annex_vii_raw.json")

    assert rules["dataset_version"] == CANDIDATE_DATASET_VERSION
    assert annex_vii["section_version"] == "2025-2, 12 December 2025"
    assert annex_vii["preamble"]
    assert {item["provision_id"] for item in provisions["provisions"]} >= {
        "sg-regulation-6-3", "sg-regulation-6-4", "sg-regulation-6-5",
    }
    positive_rules = [item for item in rules["rules"] if item["list_semantics"] == "positive_list"]
    assert positive_rules
    assert all(item["permitted_function"] for item in positive_rules)
    assert all(any(text["relationship"] == "schedule or annex preamble" for text in item["supporting_source_texts"]) for item in positive_rules)


def test_candidate_links_source_warnings_and_combined_limit_footnotes():
    document = _load(ROOT / "data_pipeline" / "candidate" / "processed" / "rules.json")
    rules = {item["rule_id"]: item for item in document["rules"]}

    formaldehyde = rules["acd-vi-20"]
    assert formaldehyde["warning_requirements"] == [{
        "warning_text": "contains formaldehyde",
        "trigger_text": "the concentration of formaldehyde in the finished product exceeds 0.05%",
        "applicability": "professional_review",
    }]

    for rule_id, footnote_number, footnote_page in (
        ("acd-vii-a29a", "2", 290),
        ("sg-third-schedule-v-a29a", "4", 195),
    ):
        rule = rules[rule_id]
        assert rule["footnotes"][0]["footnote_number"] == footnote_number
        assert rule["footnotes"][0]["source_page"] == footnote_page
        assert rule["combined_limit_requirements"][0]["constituent_references"] == ["A29", "A29a"]
        assert footnote_page in rule["source_pages"]


def test_candidate_links_acd_colourant_qualification_footnote():
    document = _load(ROOT / "data_pipeline" / "candidate" / "processed" / "rules.json")
    rule = next(item for item in document["rules"] if item["rule_id"] == "acd-iv-12085")
    assert rule["regulatory_identifiers"]["qualifications"] == ["2"]
    assert rule["footnotes"][0]["footnote_number"] == "2"
    assert rule["footnotes"][0]["source_page"] == 265


def test_candidate_has_all_five_cross_reference_directions_and_material_differences():
    document = _load(ROOT / "data_pipeline" / "candidate" / "processed" / "source_cross_references.json")
    mappings = {item["regulatory_mapping"] for item in document["cross_references"]}
    assert mappings >= {
        "annex-ii-to-third-schedule-part-i",
        "annex-iii-to-third-schedule-part-ii",
        "annex-iv-to-third-schedule-part-iii",
        "annex-vi-to-third-schedule-part-iv",
        "annex-vii-to-third-schedule-part-v",
    }
    assert any(item["material_difference"] for item in document["cross_references"])


def test_promotion_is_blocked_until_every_required_human_check_passes(monkeypatch, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(candidate_pipeline, "CANDIDATE_REPORT_ROOT", reports)
    monkeypatch.setattr(candidate_pipeline, "CANDIDATE_BASELINE_PATH", tmp_path / "candidate_hashes.json")
    with pytest.raises(RuntimeError, match="recorded PASS"):
        candidate_pipeline.promote_candidate()


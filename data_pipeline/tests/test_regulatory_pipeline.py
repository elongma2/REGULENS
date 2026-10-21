from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from data_pipeline.scripts.config import (
    ACCEPTED_BASELINE_PATH,
    EXPECTED_SOURCE_HASHES,
    PROCESSED_ROOT,
    RAW_ROOT,
    REPORT_ROOT,
)
from data_pipeline.scripts.cross_reference import compare_mapping
from data_pipeline.scripts.extract import sha256


ROOT = Path(__file__).resolve().parents[2]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_original_source_hashes_are_unchanged() -> None:
    manifest = load(RAW_ROOT / "source_manifest.json")
    by_id = {item["source_document"]: item for item in manifest["documents"]}
    for source_id, expected in EXPECTED_SOURCE_HASHES.items():
        source_path = ROOT / "data_pipeline" / "Sources" / by_id[source_id]["filename"]
        assert sha256(source_path) == expected
        assert by_id[source_id]["sha256"] == expected


def test_raw_record_counts_and_required_references() -> None:
    expected = {
        "annex_ii_raw.json": (1729, {"A1140", "391", "419", "1539", "1711"}),
        "annex_iii_raw.json": (249, {"6", "8a", "12", "13", "250", "288", "339", "342", "67 to 92", "103 to 184"}),
        "singapore_third_schedule_part_i_raw.json": (1709, {"A1140", "391", "419", "1539", "1711"}),
        "singapore_third_schedule_part_ii_raw.json": (221, {"6", "8a", "12", "250", "339"}),
    }
    for filename, (count, references) in expected.items():
        raw = load(RAW_ROOT / filename)
        assert len(raw["records"]) == count
        actual = {item["reference_number"] for item in raw["records"]}
        assert references <= actual
        assert all(page["table_count"] == 1 for page in raw["page_diagnostics"])
        assert not any(page.get("unassigned_fragments") for page in raw["page_diagnostics"])
    assert len(load(RAW_ROOT / "annex_iii_raw.json")["footnotes"]) == 23
    assert len(load(RAW_ROOT / "singapore_third_schedule_part_ii_raw.json")["footnotes"]) == 11


def test_appendix_i_category_hierarchy_is_preserved() -> None:
    raw = load(RAW_ROOT / "appendix_i_raw.json")
    assert raw["list_is_explicitly_non_exhaustive"] is True
    assert len(raw["categories"]) == 20
    hair = next(category for category in raw["categories"] if category["subcategories"])
    assert len(hair["subcategories"]) == 6
    context = load(PROCESSED_ROOT / "product_context.json")
    assert context["explicit_exclusions"] == [{
        "category_id": "appendix-i-category-02",
        "source_page": 2,
        "source_text": "Face masks (with the exception of chemical peeling products).",
        "excluded_product_text": "chemical peeling products",
    }]


def test_multiline_and_headerless_regressions() -> None:
    annex_ii = load(RAW_ROOT / "annex_ii_raw.json")
    annex_iii = load(RAW_ROOT / "annex_iii_raw.json")
    by_ii = {item["reference_number"]: item for item in annex_ii["records"]}
    by_iii = {item["reference_number"]: item for item in annex_iii["records"]}
    assert by_ii["391"]["source_pages"] == [14, 15]
    assert by_ii["1539"]["source_pages"] == list(range(74, 83))
    assert by_iii["12"]["source_pages"] == [113, 114]
    assert by_iii["250"]["source_pages"] == [181, 182]
    assert by_iii["66"]["source_pages"] == [137]
    assert by_iii["102"]["source_pages"] == [140]
    diagnostics = {item["source_page"]: item for item in annex_iii["page_diagnostics"]}
    assert diagnostics[113]["column_counts"] == [6]
    assert diagnostics[181]["column_counts"] == [6]
    assert diagnostics[252]["column_counts"] == [6]


def test_regulation_6_provisions_and_semantics() -> None:
    raw = load(RAW_ROOT / "singapore_regulation_6_raw.json")
    provisions = {item["provision_id"]: item["source_text"] for item in raw["provisions"]}
    assert "Part I of" in provisions["sg-regulation-6-1"]
    assert "trace amount" in provisions["sg-regulation-6-1"]
    compact = " ".join(provisions["sg-regulation-6-2"].split())
    assert "second column of Part II" in compact
    assert "third column" in compact
    assert "fourth column" in compact
    assert "fifth column" in compact
    assert "unwholesome cosmetic product" in provisions["sg-regulation-6-7"]


def test_case_splitting_is_conservative() -> None:
    rules_document = load(PROCESSED_ROOT / "rules.json")
    rules = rules_document["rules"]
    annex_iii = [item for item in rules if item["regulatory_section"] == "Annex III Part 1"]
    by_reference: dict[str, list[dict]] = {}
    for item in annex_iii:
        by_reference.setdefault(item["reference_number"], []).append(item)
    assert {item["case_label"] for item in by_reference["6"]} == {"a", "b"}
    assert {item["case_label"] for item in by_reference["342"]} == {"a", "b", "c"}
    assert len(by_reference["12"]) == 1
    assert by_reference["12"][0]["normalization_status"] == "manual_review_required"
    assert "multi_case_mapping_not_unambiguous" in by_reference["12"][0]["review_reasons"]
    source_footnotes = {
        item["regulatory_section"]: item["footnotes"] for item in rules_document["source_footnotes"]
    }
    assert len(source_footnotes["Annex III Part 1"]) == 23
    assert len(source_footnotes["Third Schedule Part II"]) == 11
    reference_419 = next(
        item for item in rules if item["regulatory_section"] == "Annex II Part 1" and item["reference_number"] == "419"
    )
    assert reference_419["source_pages"] == [16, 98, 99, 100, 101]
    assert len(reference_419["supporting_source_texts"]) == 4
    reference_295 = next(
        item for item in rules if item["regulatory_section"] == "Annex III Part 1" and item["reference_number"] == "295"
    )
    assert reference_295["footnotes"] == []


def test_identifiers_concentrations_and_source_column_stages() -> None:
    rules = load(PROCESSED_ROOT / "rules.json")["rules"]

    def get(section: str, reference: str, case: str | None = None) -> dict:
        return next(
            item for item in rules
            if item["regulatory_section"] == section
            and item["reference_number"] == reference
            and item["case_label"] == case
        )

    assert get("Annex III Part 1", "342", "a")["cas_numbers"] == ["128-37-0"]
    assert get("Annex II Part 1", "2")["cas_numbers"] == [
        "2260-50-6", "51-84-3", "60-31-1", "66-23-9", "927-86-6"
    ]
    assert "38304-91-5" in get("Annex II Part 1", "372")["cas_numbers"]
    assert get("Annex III Part 1", "8a")["cas_numbers"] == [
        "106-50-3", "16245-77-5", "624-18-0"
    ]
    assert get("Annex III Part 1", "331")["cas_numbers"] == ["220158-86-1"]
    acd_102 = get("Annex III Part 1", "102")
    assert acd_102["concentration"]["value"] == 100
    assert acd_102["concentration"]["unit"] == "mg/kg"
    assert acd_102["concentration"]["preparation_stage"] == "ready_for_use"
    assert get("Annex III Part 1", "342", "a")["concentration"]["preparation_stage"] == "ready_for_use"
    assert get("Third Schedule Part II", "339", "a")["concentration"]["preparation_stage"] == "finished_product"
    assert get("Annex III Part 1", "223")["concentration"]["basis"] == "sulphate"
    assert get("Third Schedule Part II", "322")["concentration"]["unit"] == "ppm"
    assert get("Annex III Part 1", "9a")["normalization_status"] == "manual_review_required"
    assert "concentration_condition_not_normalized" in get("Annex III Part 1", "9a")["review_reasons"]


def test_ambiguous_case_mappings_are_not_actionable() -> None:
    rules = load(PROCESSED_ROOT / "rules.json")["rules"]
    by_id = {item["rule_id"]: item for item in rules}
    for rule_id in ("acd-iii-8c", "acd-iii-334"):
        rule = by_id[rule_id]
        assert rule["normalization_status"] == "manual_review_required"
        assert rule["concentration"] is None
        assert "multi_case_mapping_not_unambiguous" in rule["review_reasons"]
        assert "ambiguous_multi_case_concentration_not_normalized" in rule["review_reasons"]


def test_conditional_annex_ii_prohibitions_require_review() -> None:
    rules = load(PROCESSED_ROOT / "rules.json")["rules"]
    by_id = {item["rule_id"]: item for item in rules}
    for rule_id in ("acd-ii-a1140", "acd-ii-360", "sg-third-schedule-i-a1140"):
        rule = by_id[rule_id]
        assert rule["normalization_status"] == "manual_review_required"
        assert "conditional_prohibition_wording_not_structured" in rule["review_reasons"]
    cas_scope = by_id["acd-ii-327"]
    assert "non_exhaustive_identifier_scope_not_structured" in cas_scope["review_reasons"]
    assert "conditional_prohibition_wording_not_structured" not in cas_scope["review_reasons"]


def _rule(section: str, reference: str, name: str, prefix: str) -> dict:
    return {
        "regulatory_section": section,
        "reference_number": reference,
        "active": True,
        "substance_name": name,
        "rule_id": f"{prefix}-{reference.casefold()}",
        "case_label": None,
    }


def test_cross_reference_statuses_include_bounded_singapore_only_case() -> None:
    rules = [
        _rule("Annex II Part 1", "1", "Same", "acd-ii"),
        _rule("Third Schedule Part I", "1", "Same", "sg-third-schedule-i"),
        _rule("Annex II Part 1", "2", "Old wording", "acd-ii"),
        _rule("Third Schedule Part I", "2", "New wording", "sg-third-schedule-i"),
        _rule("Annex II Part 1", "3", "ACD only", "acd-ii"),
        _rule("Third Schedule Part I", "4", "Singapore only", "sg-third-schedule-i"),
        _rule("Annex II Part 1", "5-6", "", "acd-ii"),
    ]
    compared = compare_mapping(rules, "Annex II Part 1", "Third Schedule Part I", "annex-ii-to-third-schedule-part-i")
    statuses = Counter(item.comparison_status for item in compared)
    assert statuses == Counter({"aligned": 1, "changed": 1, "acd_only": 1, "singapore_only": 1, "ambiguous": 1})


def test_generated_validation_passes_and_has_all_spot_checks() -> None:
    report = load(REPORT_ROOT / "validation_report.json")
    checklist = load(REPORT_ROOT / "manual_spot_check_checklist.json")
    results = load(REPORT_ROOT / "manual_spot_check_results.json")
    assert report["validation_status"] == "passed"
    assert not report["errors"]
    assert checklist["check_count"] == 35
    assert len(checklist["checks"]) == 35
    assert report["counts"]["completed_spot_checks"] == 35
    assert results["summary"] == {"total": 35, "passed": 35, "failed": 0, "pending": 0}
    assert {item["check_id"] for item in results["results"]} == {
        item["check_id"] for item in checklist["checks"]
    }


def test_current_dataset_exposes_expected_cross_reference_classes() -> None:
    xrefs = load(PROCESSED_ROOT / "source_cross_references.json")["cross_references"]
    statuses = Counter(item["comparison_status"] for item in xrefs)
    assert statuses["aligned"] > 0
    assert statuses["changed"] > 0
    assert statuses["acd_only"] > 0
    assert statuses["ambiguous"] > 0
    assert statuses["singapore_only"] == 0
    a10 = next(
        item for item in xrefs
        if item["regulatory_mapping"] == "annex-iii-to-third-schedule-part-ii"
        and item["reference_number"] == "A10"
    )
    assert a10["comparison_status"] == "changed"
    assert "concentration" in a10["field_differences"]


def test_accepted_output_baseline_matches_generated_files() -> None:
    report = load(REPORT_ROOT / "validation_report.json")
    baseline = load(ACCEPTED_BASELINE_PATH)
    assert report["accepted_baseline_status"] == "matched"
    assert baseline["dataset_version"] == report["dataset_version"]
    assert baseline["generated_output_hashes"] == report["generated_output_hashes"]

from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

import pytest

from backend.app.services.ingredient_linkage import (
    AcceptedIngredientLinkageError,
    load_accepted_ingredient_linkages,
)
from data_pipeline.identity.eu_singapore_linkage.scripts.pipeline import (
    LinkageValidationError,
    build_review_queue,
    validate_review_input,
)


ROOT = Path(__file__).resolve().parents[4]


def bindings() -> dict:
    return {
        "identity_dataset_version": "eu-glossary-2025-1175",
        "identity_dataset_hash": "e146c81b5978c373ac1f20c677ba20c5221e02b7f128b4b095ff711075331094",
        "singapore_regulatory_baseline": "acd-2026-1__sg-2025-12-01__parts-i-v-r1",
        "singapore_regulatory_baseline_hash": hashlib.sha256(
            (ROOT / "data_pipeline" / "accepted_output_hashes.json").read_bytes()
        ).hexdigest(),
        "screened_scope": [
            "Third Schedule Part I", "Third Schedule Part II", "Third Schedule Part III",
            "Third Schedule Part IV", "Third Schedule Part V",
        ],
    }


def reviewed_decision(**updates) -> dict:
    value = {
        "catalogue_ingredient_id": "eu-2025-1175-entry-17380",
        "catalogue_canonical_name": "NIACINAMIDE",
        "status": "verified_not_represented",
        "singapore_raw_record_ids": [],
        "review": {
            "reviewed": True,
            "reviewed_at": "2026-09-16",
            "reviewer": "Test reviewer",
            "review_basis": "Compared against accepted Third Schedule Parts I and II.",
            "notes": "Test-only reviewed input.",
        },
    }
    value.update(updates)
    return value


def review_input(*decisions: dict) -> dict:
    return {**bindings(), "decisions": list(decisions)}


def test_accepted_linkage_manifest_contains_only_source_approved_records():
    store = load_accepted_ingredient_linkages(ROOT)
    assert store.counts == {
        "accepted_records": 2,
        "linked": 2,
        "verified_not_represented": 0,
        "unresolved": 0,
    }
    assert set(store.records_by_catalogue_id) == {
        "eu-2025-1175-entry-17797",
        "eu-2025-1175-entry-20709",
    }
    octocrylene = store.records_by_catalogue_id["eu-2025-1175-entry-17797"]
    assert octocrylene["supported_cas_numbers"] == ["6197-30-4"]
    assert {item["rule_id"] for item in octocrylene["singapore_targets"]} == {
            "sg-third-schedule-v-10-case-a",
            "sg-third-schedule-v-10-case-b",
    }


def test_linkage_loader_rejects_modified_accepted_output(tmp_path):
    source = ROOT / "data_pipeline" / "identity" / "eu_singapore_linkage" / "accepted"
    target = tmp_path / "data_pipeline" / "identity" / "eu_singapore_linkage" / "accepted"
    target.mkdir(parents=True)
    shutil.copy(source / "accepted_linkage_hashes.json", target)
    shutil.copy(source / "linkages.json", target)
    (target / "linkages.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(AcceptedIngredientLinkageError, match="hash mismatch"):
        load_accepted_ingredient_linkages(tmp_path)


def test_review_queue_contains_only_the_unpromoted_ci_42090_candidate():
    first = build_review_queue(ROOT)
    second = build_review_queue(ROOT)
    assert first == second
    assert first["candidate_count"] == 1
    assert {item["catalogue_canonical_name"] for item in first["records"]} == {
        "CI 42090"
    }
    assert all(item["current_status"] == "unresolved" for item in first["records"])
    ci_42090 = first["records"][0]
    assert ci_42090["supported_cas_numbers"] == [
        "2650-18-2",
        "3844-45-9",
        "68921-42-6",
    ]


def test_octocrylene_source_keeps_the_singapore_benzophenone_trace_footnote():
    raw = json.loads(
        (ROOT / "data_pipeline" / "raw" / "singapore_third_schedule_part_v_raw.json").read_text(
            encoding="utf-8"
        )
    )
    footnote = next(item for item in raw["footnotes"] if item.get("footnote_number") == "7")
    assert footnote["source_page"] == 195
    assert "Benzophenone as an impurity and/or degradation product of Octocrylene" in footnote["source_text"]
    assert "must be kept at trace level" in footnote["source_text"]


def test_reviewed_absence_and_multitarget_link_are_derived_deterministically():
    linked = reviewed_decision(
        catalogue_ingredient_id="eu-2025-1175-entry-08587",
        catalogue_canonical_name="DIETHYLENE GLYCOL",
        status="linked",
        singapore_raw_record_ids=[
            "raw-singapore_regulations_2025_12_01-third-schedule-part-i-a1140",
            "raw-singapore_regulations_2025_12_01-third-schedule-part-ii-186",
        ],
    )
    first = validate_review_input(review_input(reviewed_decision(), linked), ROOT)
    second = validate_review_input(review_input(reviewed_decision(), linked), ROOT)
    assert first == second
    assert first["counts"] == {
        "accepted_records": 2,
        "linked": 1,
        "verified_not_represented": 1,
        "unresolved": 0,
    }
    record = next(item for item in first["records"] if item["status"] == "linked")
    assert {target["rule_id"] for target in record["singapore_targets"]} == {
        "sg-third-schedule-i-a1140",
        "sg-third-schedule-ii-186",
    }


@pytest.mark.parametrize(
    "decision, message",
    [
        (reviewed_decision(status="linked"), "require at least one"),
        (
            reviewed_decision(
                singapore_raw_record_ids=[
                    "raw-singapore_regulations_2025_12_01-third-schedule-part-i-a1136"
                ]
            ),
            "cannot contain accepted",
        ),
        (reviewed_decision(review={"reviewed": False}), "review.reviewed=true"),
        (reviewed_decision(catalogue_canonical_name="Niacinamide"), "does not match"),
    ],
)
def test_malformed_professional_decisions_fail_clearly(decision, message):
    with pytest.raises(LinkageValidationError, match=message):
        validate_review_input(review_input(decision), ROOT)


def test_duplicate_decisions_and_stale_bindings_are_rejected():
    decision = reviewed_decision()
    with pytest.raises(LinkageValidationError, match="Duplicate"):
        validate_review_input(review_input(decision, decision), ROOT)
    stale = review_input(decision)
    stale["identity_dataset_hash"] = "0" * 64
    with pytest.raises(LinkageValidationError, match="identity_dataset_hash"):
        validate_review_input(stale, ROOT)


def test_regulatory_and_identity_accepted_manifests_remain_the_known_inputs():
    regulatory = json.loads((ROOT / "data_pipeline" / "accepted_output_hashes.json").read_text())
    identity = json.loads(
        (
            ROOT
            / "data_pipeline"
            / "identity"
            / "eu_common_ingredient_glossary"
            / "accepted"
            / "accepted_identity_hashes.json"
        ).read_text()
    )
    assert len(regulatory["generated_output_hashes"]) == 18
    assert identity["counts"]["searchable_identities"] == 30416

from __future__ import annotations

from backend.app.models.screening import ConcentrationInput, Finding, IngredientInput, RegulatedFunction
from backend.app.services.compliance import screen_ingredient
from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.ingredient_linkage import (
    IngredientLinkageStore,
    load_accepted_ingredient_linkages,
)
from backend.app.services.loader import load_accepted_store
from backend.app.services.resolver import resolve_ingredient
from data_pipeline.identity.eu_singapore_linkage.scripts.pipeline import build_review_queue


def candidate_linkage_store() -> IngredientLinkageStore:
    store = load_accepted_store()
    accepted = load_accepted_ingredient_linkages()
    queue = build_review_queue()
    records = dict(accepted.records_by_catalogue_id)
    for candidate in queue["records"]:
        record = {
            key: queue[key]
            for key in (
                "identity_dataset_version", "identity_dataset_hash",
                "singapore_regulatory_baseline", "singapore_regulatory_baseline_hash",
                "screened_scope",
            )
        }
        record.update({
            "linkage_id": f"test-{candidate['catalogue_ingredient_id']}",
            "catalogue_ingredient_id": candidate["catalogue_ingredient_id"],
            "catalogue_canonical_name": candidate["catalogue_canonical_name"],
            "status": "linked",
            "singapore_targets": candidate["proposed_singapore_targets"],
            "supported_names": candidate["supported_names"],
            "supported_cas_numbers": candidate["supported_cas_numbers"],
            "supported_ci_numbers": candidate["supported_ci_numbers"],
            "supporting_acd_records": candidate["supporting_acd_records"],
            "review": {
                "reviewed": True,
                "reviewed_at": "2026-11-04",
                "reviewer": "Test fixture",
                "review_basis": "Synthetic accepted-linkage fixture built from the candidate queue.",
                "notes": "Not an accepted production decision.",
            },
        })
        records[record["catalogue_ingredient_id"]] = record
    return IngredientLinkageStore(
        root=store.root,
        dataset_version=queue["dataset_version"],
        baseline_manifest_hash="test-only",
        identity_dataset_version=queue["identity_dataset_version"],
        identity_dataset_hash=queue["identity_dataset_hash"],
        singapore_regulatory_baseline=queue["singapore_regulatory_baseline"],
        singapore_regulatory_baseline_hash=queue["singapore_regulatory_baseline_hash"],
        screened_scope=tuple(queue["screened_scope"]),
        counts={"accepted_records": 3, "linked": 3, "verified_not_represented": 0, "unresolved": 0},
        records_by_catalogue_id=records,
    )


def test_confirmed_candidate_groups_resolve_all_regulatory_records():
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    linkages = candidate_linkage_store()
    cases = [
        ("PHENOXYETHANOL", "122-99-6", ["sg-third-schedule-iv-29"]),
        ("OCTOCRYLENE", "6197-30-4", ["sg-third-schedule-v-10-case-a", "sg-third-schedule-v-10-case-b"]),
        ("CI 42090", "3844-45-9", ["sg-third-schedule-ii-190", "sg-third-schedule-iii-42090"]),
    ]
    for name, cas, expected_rules in cases:
        result = resolve_ingredient(store, name, cas, catalogue, linkage_store=linkages)
        assert result.status.value == "resolved"
        assert result.applicable_regulatory_record_ids == expected_rules
    ci = resolve_ingredient(store, "CI 42090", "3844-45-9", catalogue, linkage_store=linkages)
    assert ci.identity_outcome.value == "same_identity_multiple_regulatory_records"


def test_current_accepted_runtime_activates_two_links_and_keeps_ci_42090_pending():
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    linkages = load_accepted_ingredient_linkages()

    phenoxyethanol = resolve_ingredient(
        store, "PHENOXYETHANOL", "122-99-6", catalogue, linkage_store=linkages
    )
    octocrylene = resolve_ingredient(
        store, "OCTOCRYLENE", "6197-30-4", catalogue, linkage_store=linkages
    )
    ci_42090 = resolve_ingredient(
        store, "CI 42090", "3844-45-9", catalogue, linkage_store=linkages
    )

    assert phenoxyethanol.identity_outcome.value == "identity_verified"
    assert phenoxyethanol.applicable_regulatory_record_ids == ["sg-third-schedule-iv-29"]
    assert octocrylene.identity_outcome.value == "identity_verified"
    assert octocrylene.applicable_regulatory_record_ids == [
        "sg-third-schedule-v-10-case-a", "sg-third-schedule-v-10-case-b"
    ]
    assert ci_42090.identity_outcome.value == "related_distinct_forms"
    assert ci_42090.status.value == "ambiguous"
    assert "eu-2025-1175-entry-06401" not in linkages.records_by_catalogue_id


def test_confirmed_groups_reach_preservative_uv_and_colourant_evaluation():
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    linkages = candidate_linkage_store()
    concentration = ConcentrationInput(
        value=0.2, unit="percent", basis=None, preparation_stage="finished_product"
    )
    inputs = [
        IngredientInput(name="PHENOXYETHANOL", cas_number="122-99-6", concentration=concentration, regulated_functions=[RegulatedFunction.PRESERVATIVE]),
        IngredientInput(name="OCTOCRYLENE", cas_number="6197-30-4", concentration=concentration, regulated_functions=[RegulatedFunction.UV_FILTER]),
        IngredientInput(name="CI 42090", cas_number="3844-45-9", concentration=concentration, regulated_functions=[RegulatedFunction.COLOURANT]),
    ]
    expected = [
        {"sg-third-schedule-iv-29"},
        {"sg-third-schedule-v-10-case-a", "sg-third-schedule-v-10-case-b"},
        {"sg-third-schedule-ii-190", "sg-third-schedule-iii-42090"},
    ]
    expected_dispositions = ["fully_evaluated", "partially_evaluated", "partially_evaluated"]
    for ingredient, rule_ids, disposition in zip(inputs, expected, expected_dispositions, strict=True):
        result = screen_ingredient(store, ingredient, ingredient_catalog=catalogue, linkage_store=linkages)
        assert rule_ids <= {item.rule_id for item in result.rule_evaluations}
        assert result.screening_disposition.value == disposition


def test_phenoxyethanol_without_function_discovers_and_assesses_preservative_rule():
    result = screen_ingredient(
        load_accepted_store(),
        IngredientInput(
            name="PHENOXYETHANOL",
            cas_number="122-99-6",
            concentration=ConcentrationInput(
                concentration_type="range",
                lower_bound=1.05,
                upper_bound=1.15,
                lower_inclusive=True,
                upper_inclusive=True,
                unit="percent",
                basis=None,
                preparation_stage="finished_product",
            ),
        ),
        ingredient_catalog=load_accepted_ingredient_catalog(),
        linkage_store=load_accepted_ingredient_linkages(),
    )

    candidate = next(
        item for item in result.rule_evaluations
        if item.rule_id == "sg-third-schedule-iv-29"
    )
    assert result.primary_finding != Finding.NO_ISSUE
    assert candidate.evaluation_status == "deterministic"
    assert candidate.finding == Finding.PERMITTED_USE_CONDITION_NOT_MET
    assert result.function_evaluations[0].regulated_function == RegulatedFunction.PRESERVATIVE
    assert result.function_evaluations[0].status == "not_satisfied"
    assert not any(item.code == "regulated_function_missing" for item in result.review_issues)


def test_exact_catalogue_names_with_unmapped_cas_remain_resolved_without_false_conflict():
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    for name, cas in (("AQUA", "7732-18-5"), ("PANTHENOL", "81-13-0"), ("GLYCERIN", "56-81-5")):
        result = resolve_ingredient(store, name, cas, catalogue)
        assert result.status.value == "resolved"
        assert result.identity_outcome.value == "name_recognised_cas_unverified"
        assert "conflict" not in " ".join(result.reasons)


def test_known_name_cas_conflict_remains_ambiguous():
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    result = resolve_ingredient(store, "Aminophylline", "58-55-9", catalogue)
    assert result.status.value == "ambiguous"
    assert result.identity_outcome.value == "genuine_name_cas_conflict"


def test_octocrylene_uses_the_applicable_branch_and_exposes_footnote_seven():
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    linkages = load_accepted_ingredient_linkages()
    ingredient = IngredientInput(
        name="OCTOCRYLENE",
        cas_number="6197-30-4",
        concentration=ConcentrationInput(
            value=8, unit="percent", basis=None, preparation_stage="finished_product"
        ),
        regulated_functions=[RegulatedFunction.UV_FILTER],
    )

    result = screen_ingredient(
        store,
        ingredient,
        product_applicability={"spray_or_aerosol": False},
        ingredient_catalog=catalogue,
        linkage_store=linkages,
    )

    evaluations = {item.rule_id: item for item in result.rule_evaluations}
    assert evaluations["sg-third-schedule-v-10-case-a"].evaluation_status == "not_applicable_to_submitted_context"
    assert evaluations["sg-third-schedule-v-10-case-b"].evaluation_status == "withheld_professional_review"
    assert evaluations["sg-third-schedule-v-10-case-b"].evidence.concentration["value"] == 10
    assert evaluations["sg-third-schedule-v-10-case-b"].evidence.footnotes[0]["footnote_number"] == "7"
    assert result.screening_disposition.value == "partially_evaluated"
    assert "impurity_trace_requirement" in {item.code for item in result.review_issues}
    assert "source_difference_material" not in {item.code for item in result.review_issues}
    assert not any(
        item.rule_id == "sg-third-schedule-v-10-case-a"
        for item in result.review_issues
    )

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.models.document_intake import (
    CalculatedContribution,
    CompositionLegend,
    CompositionLegendEntry,
    CompositionQuantity,
    ConfirmationStatus,
    DisclosureStatus,
    DirectIngredient,
    MaterialConstituent,
    SupplierMaterial,
)
from backend.app.models.formulation import FormulationConcentration, FormulationIngredientRequest
from backend.app.services.composition_legends import resolve_coded_quantity
from backend.app.services.material_calculation import (
    add_percentage_quantities,
    aggregate_contributions,
    calculate_material_contributions,
    multiply_percentage_quantities,
    validate_material_composition,
)
from backend.app.services.formulation_assembly import prepare_assembly
from backend.app.services.formulation import screen_formulation
from backend.app.services.loader import load_accepted_store


ROOT = Path(__file__).resolve().parents[2]


def quantity(kind: str, **values) -> CompositionQuantity:
    return CompositionQuantity.model_validate({"kind": kind, **values})


def constituent(
    row_id: str,
    name: str,
    composition: CompositionQuantity | None,
    *,
    identity: str | None = None,
) -> MaterialConstituent:
    return MaterialConstituent(
        constituent_id=row_id,
        submitted_name=name,
        composition_quantity=composition,
        verified_identity_group=identity,
    )


def material(*rows: MaterialConstituent, complete: bool = True) -> SupplierMaterial:
    return SupplierMaterial(
        material_id="material-1",
        trade_name="OPTASENSE",
        supplier_name="Supplier",
        finished_product_usage=quantity(
            "exact",
            value=2.0,
            unit="percent",
            quantity_scope="finished_product",
            preparation_stage="finished_product",
            raw_text="2%",
        ),
        attached_document_ids=["doc-1"],
        governing_document_id="doc-1",
        constituents=list(rows),
        disclosure_status=DisclosureStatus.COMPLETE if complete else DisclosureStatus.PARTIAL,
        confirmation_status=ConfirmationStatus.CONFIRMED,
    )


def test_document_local_legend_resolves_coded_range():
    coded = quantity("coded_range", reported_code=" C ", raw_text="C")
    legend = CompositionLegend(
        legend_id="legend-1",
        document_id="doc-1",
        entries=[CompositionLegendEntry(
            entry_id="legend-1:C",
            code="C",
            raw_definition="C = 25-50%",
            normalized_quantity=quantity(
                "range",
                lower=25.0,
                upper=50.0,
                unit="percent",
                quantity_scope="supplier_material",
            ),
        )],
    )

    resolved, issues = resolve_coded_quantity(
        coded,
        legend,
        document_id="doc-1",
        material_id="material-1",
        constituent_id="constituent-1",
    )

    assert issues == []
    assert resolved is not None
    assert resolved.kind.value == "range"
    assert resolved.lower == 25
    assert resolved.upper == 50
    assert resolved.reported_code == "C"
    assert resolved.legend_entry_id == "legend-1:C"


def test_lumimatrix_document_codes_produce_finished_product_intervals() -> None:
    legend = CompositionLegend(
        legend_id="lumimatrix:legend",
        document_id="lumimatrix-rev-a",
        entries=[
            CompositionLegendEntry(
                entry_id="lumimatrix:legend:C",
                code="C",
                raw_definition="C = 25-50%",
                normalized_quantity=quantity(
                    "range", lower=25.0, upper=50.0, unit="percent",
                    quantity_scope="supplier_material",
                ),
            ),
            CompositionLegendEntry(
                entry_id="lumimatrix:legend:F",
                code="F",
                raw_definition="F = 1-5%",
                normalized_quantity=quantity(
                    "range", lower=1.0, upper=5.0, unit="percent",
                    quantity_scope="supplier_material",
                ),
            ),
        ],
    )
    usage = quantity(
        "exact", value=4.0, unit="percent", quantity_scope="finished_product",
        preparation_stage="finished_product", raw_text="4%",
    )
    carbomer, carbomer_issues = resolve_coded_quantity(
        quantity("coded_range", reported_code="F", raw_text="F"),
        legend,
        document_id="lumimatrix-rev-a",
    )
    aqua, aqua_issues = resolve_coded_quantity(
        quantity("coded_range", reported_code="C", raw_text="C"),
        legend,
        document_id="lumimatrix-rev-a",
    )

    assert carbomer_issues == [] and carbomer is not None
    assert aqua_issues == [] and aqua is not None
    carbomer_finished = multiply_percentage_quantities(usage, carbomer)
    aqua_supplier = multiply_percentage_quantities(usage, aqua)
    aqua_combined = add_percentage_quantities([
        quantity(
            "unknown", unit="percent", quantity_scope="finished_product",
            preparation_stage="finished_product", raw_text="q.s. to 100%",
        ),
        aqua_supplier,
    ])

    assert carbomer_finished.lower == pytest.approx(0.04)
    assert carbomer_finished.upper == pytest.approx(0.20)
    assert aqua_supplier.lower == pytest.approx(1.0)
    assert aqua_supplier.upper == pytest.approx(2.0)
    assert aqua_combined.kind.value == "lower_bound"
    assert aqua_combined.lower == pytest.approx(1.0)
    assert aqua_combined.upper is None


def test_coded_range_without_same_document_legend_is_blocked():
    resolved, issues = resolve_coded_quantity(
        quantity("coded_range", reported_code="C"),
        None,
        document_id="doc-1",
        constituent_id="constituent-1",
    )
    assert resolved is None
    assert issues[0].code == "missing_legend"
    assert issues[0].blocking_for_calculation is True


def test_range_contribution_multiplies_without_losing_bounds():
    result = multiply_percentage_quantities(
        quantity(
            "exact", value=2.0, unit="percent", quantity_scope="finished_product",
            preparation_stage="finished_product", raw_text="2%",
        ),
        quantity(
            "range", lower=25.0, upper=50.0, unit="percent",
            quantity_scope="supplier_material", raw_text="25-50%",
        ),
    )
    assert result.kind.value == "range"
    assert result.lower == pytest.approx(0.5)
    assert result.upper == pytest.approx(1.0)
    assert result.quantity_scope == "finished_product"


def test_qsp_is_derived_only_from_complete_bounded_disclosure():
    source = material(
        constituent(
            "a", "A", quantity("exact", value=25.0, unit="percent", quantity_scope="supplier_material"),
        ),
        constituent(
            "b", "B", quantity("range", lower=10.0, upper=20.0, unit="percent", quantity_scope="supplier_material"),
        ),
        constituent(
            "water", "AQUA", quantity(
                "remainder_to_total", value=100.0, unit="percent", quantity_scope="supplier_material", raw_text="qsp 100",
            ),
        ),
    )
    validated, issues = validate_material_composition(source)
    derived = next(row.composition_quantity for row in validated.constituents if row.constituent_id == "water")
    assert issues == []
    assert derived.kind.value == "range"
    assert derived.lower == pytest.approx(55)
    assert derived.upper == pytest.approx(65)


def test_qsp_in_partial_disclosure_remains_blocked():
    source = material(
        constituent(
            "a", "A", quantity("exact", value=25.0, unit="percent", quantity_scope="supplier_material"),
        ),
        constituent(
            "water", "AQUA", quantity(
                "remainder_to_total", value=100.0, unit="percent", quantity_scope="supplier_material",
            ),
        ),
        complete=False,
    )
    _, issues = validate_material_composition(source)
    assert issues[0].code == "impossible_composition_total"
    assert issues[0].blocking_for_calculation is True


def test_impossible_minimum_total_is_rejected_but_overlapping_upper_ranges_are_not():
    impossible = material(
        constituent("a", "A", quantity("range", lower=60.0, upper=70.0, unit="percent", quantity_scope="supplier_material")),
        constituent("b", "B", quantity("range", lower=50.0, upper=60.0, unit="percent", quantity_scope="supplier_material")),
    )
    _, impossible_issues = validate_material_composition(impossible)
    assert [issue.code for issue in impossible_issues] == ["impossible_composition_total"]

    overlapping = material(
        constituent("a", "A", quantity("range", lower=10.0, upper=70.0, unit="percent", quantity_scope="supplier_material")),
        constituent("b", "B", quantity("range", lower=20.0, upper=60.0, unit="percent", quantity_scope="supplier_material")),
        complete=False,
    )
    _, overlapping_issues = validate_material_composition(overlapping)
    assert all(issue.code != "impossible_composition_total" for issue in overlapping_issues)


def test_complete_supplier_statement_below_100_is_a_coverage_limitation() -> None:
    source = material(
        constituent(
            "a", "A",
            quantity("exact", value=40.0, unit="percent", quantity_scope="supplier_material"),
            identity="identity:a",
        ),
        constituent(
            "b", "B",
            quantity("exact", value=20.0, unit="percent", quantity_scope="supplier_material"),
            identity="identity:b",
        ),
    )

    _, contributions, issues = calculate_material_contributions(source)

    assert len(contributions) == 2
    limitation = next(issue for issue in issues if issue.code == "incomplete_supplier_disclosure")
    assert limitation.severity.value == "warning"
    assert limitation.blocking_for_calculation is False
    assert "will not invent" in limitation.reviewer_action


def test_partial_disclosure_preserves_supported_rows_without_mandatory_correction() -> None:
    source = material(
        constituent(
            "known", "GLYCERIN",
            quantity("range", lower=25.0, upper=50.0, unit="percent", quantity_scope="supplier_material"),
            identity="catalogue:glycerin",
        ),
        constituent("proprietary", "PROPRIETARY CONSTITUENT", None),
        complete=False,
    )

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[],
        materials=[source],
        source_document_ids=["doc-1"],
    )

    assert prepared.formulation is not None
    assert [row.name for row in prepared.formulation.ingredients] == ["GLYCERIN"]
    assert prepared.formulation.assembly_scope is not None
    assert prepared.formulation.assembly_scope.action_required_codes == []
    assert "incomplete_supplier_disclosure" in (
        prepared.formulation.assembly_scope.coverage_limitation_codes
    )
    assert any(
        code in prepared.formulation.assembly_scope.coverage_limitation_codes
        for code in ("constituent_identity_unresolved", "constituent_concentration_missing")
    )


def test_supplier_percentage_above_100_is_an_actionable_invalid_bound() -> None:
    source = material(
        constituent(
            "a", "A",
            quantity("range", lower=20.0, upper=120.0, unit="percent", quantity_scope="supplier_material"),
            identity="identity:a",
        ),
        complete=False,
    )

    _, issues = validate_material_composition(source)

    invalid = next(issue for issue in issues if issue.code == "invalid_concentration_bound")
    assert invalid.severity.value == "error"
    assert invalid.blocking_for_calculation is True


def test_material_calculation_preserves_unresolved_constituent_as_issue():
    source = material(
        constituent(
            "resolved", "GLYCERIN",
            quantity("range", lower=25.0, upper=50.0, unit="percent", quantity_scope="supplier_material"),
            identity="catalogue:glycerin",
        ),
        constituent(
            "unknown", "Mystery",
            quantity("exact", value=5.0, unit="percent", quantity_scope="supplier_material"),
        ),
        complete=False,
    )
    _, contributions, issues = calculate_material_contributions(source)
    assert len(contributions) == 1
    assert contributions[0].finished_product_quantity.lower == pytest.approx(0.5)
    assert contributions[0].finished_product_quantity.upper == pytest.approx(1.0)
    assert contributions[0].calculation_formula == "2% × 25–50% ÷ 100 = 0.5–1%"
    assert any(issue.code == "constituent_identity_unresolved" for issue in issues)


def test_incompatible_basis_is_not_silently_converted():
    source = material(
        constituent(
            "a", "A",
            quantity("exact", value=25.0, unit="mg/kg", quantity_scope="supplier_material"),
            identity="identity:a",
        ),
        complete=False,
    )
    _, contributions, issues = calculate_material_contributions(source)
    assert contributions == []
    assert any(issue.code == "incompatible_quantity_basis" for issue in issues)


def contribution(
    contribution_id: str,
    identity: str,
    result: CompositionQuantity,
    *,
    material_id: str,
) -> CalculatedContribution:
    return CalculatedContribution(
        contribution_id=contribution_id,
        source_type="material_constituent",
        source_material_id=material_id,
        source_constituent_id=f"{material_id}-constituent",
        governing_document_id=f"{material_id}-document",
        verified_identity_group=identity,
        display_name="GLYCERIN",
        finished_product_quantity=result,
        calculation_formula="test",
    )


def test_verified_identity_contributions_are_aggregated_as_intervals():
    first = contribution(
        "one", "catalogue:glycerin",
        quantity(
            "range", lower=0.5, upper=1.0, unit="percent",
            quantity_scope="finished_product", preparation_stage="finished_product", raw_text="0.5-1%",
        ),
        material_id="m1",
    )
    second = contribution(
        "two", "catalogue:glycerin",
        quantity(
            "exact", value=0.2, unit="percent",
            quantity_scope="finished_product", preparation_stage="finished_product", raw_text="0.2%",
        ),
        material_id="m2",
    )
    aggregates, issues = aggregate_contributions([first, second])
    assert issues == []
    assert len(aggregates) == 1
    assert aggregates[0].aggregate_quantity.lower == pytest.approx(0.7)
    assert aggregates[0].aggregate_quantity.upper == pytest.approx(1.2)
    assert len(aggregates[0].contributions) == 2


def test_incompatible_semantics_are_not_aggregated():
    percent = contribution(
        "one", "catalogue:glycerin",
        quantity(
            "exact", value=1.0, unit="percent",
            quantity_scope="finished_product", preparation_stage="finished_product",
        ),
        material_id="m1",
    )
    ppm = contribution(
        "two", "catalogue:glycerin",
        quantity(
            "exact", value=1.0, unit="ppm",
            quantity_scope="finished_product", preparation_stage="finished_product",
        ),
        material_id="m2",
    )
    aggregates, issues = aggregate_contributions([percent, ppm])
    assert aggregates == []
    assert issues[0].code == "unverified_identity_aggregation"


def test_addition_preserves_approximate_qualifier():
    result = add_percentage_quantities([
        quantity(
            "approximate", value=1.0, unit="percent", quantity_scope="finished_product",
            preparation_stage="finished_product", raw_text="approximately 1%",
        ),
        quantity(
            "exact", value=0.5, unit="percent", quantity_scope="finished_product",
            preparation_stage="finished_product", raw_text="0.5%",
        ),
    ])
    assert result.kind.value == "approximate"
    assert result.value == pytest.approx(1.5)
    assert result.approximate is True


def test_assembly_aggregates_direct_and_trade_material_contributions():
    direct = DirectIngredient(
        ingredient_id="direct-1",
        source_document_id="formulation-doc",
        verified_identity_group="catalogue:glycerin",
        ingredient=FormulationIngredientRequest(
            name="GLYCERIN",
            cas_number="56-81-5",
            concentration=FormulationConcentration(
                concentration_type="exact",
                value=1.0,
                unit="percent",
                basis=None,
                preparation_stage="finished_product",
                original_text="1%",
            ),
        ),
    )
    blend = material(constituent(
        "blend-glycerin",
        "GLYCERIN",
        quantity(
            "exact", value=100.0, unit="percent", quantity_scope="supplier_material", raw_text="100%",
        ),
        identity="catalogue:glycerin",
    ))
    blend.constituents[0].cas_number = "56-81-5"

    prepared = prepare_assembly(
        assembly_revision=3,
        direct_ingredients=[direct],
        materials=[blend],
        formulation_name="Pilot serum",
    )

    assert prepared.result.completeness.value == "complete"
    assert prepared.formulation is not None
    assert len(prepared.formulation.ingredients) == 1
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration.concentration_type.value == "exact"
    assert concentration.value == pytest.approx(3.0)
    assert concentration.original_text is None
    assert len(prepared.result.included_ingredients[0].contributions) == 2


def test_assembly_aggregates_direct_and_multiple_supplier_materials() -> None:
    direct = DirectIngredient(
        ingredient_id="direct-phenoxyethanol",
        source_document_id="finished-formula",
        verified_identity_group="catalogue:phenoxyethanol",
        ingredient=FormulationIngredientRequest(
            name="PHENOXYETHANOL",
            cas_number="122-99-6",
            concentration=FormulationConcentration(
                concentration_type="exact",
                value=0.3,
                unit="percent",
                basis=None,
                preparation_stage="finished_product",
                original_text="0.30%",
            ),
        ),
    )
    preserva = material(constituent(
        "preserva-phenoxyethanol",
        "PHENOXYETHANOL",
        quantity(
            "exact", value=90.0, unit="percent",
            quantity_scope="supplier_material", raw_text="90%",
        ),
        identity="catalogue:phenoxyethanol",
    )).model_copy(update={
        "material_id": "preserva-px",
        "trade_name": "Preserva PX",
        "governing_document_id": "preserva-document",
        "attached_document_ids": ["preserva-document"],
        "finished_product_usage": quantity(
            "exact", value=0.8, unit="percent",
            quantity_scope="finished_product", preparation_stage="finished_product", raw_text="0.8%",
        ),
    })
    booster = material(constituent(
        "booster-phenoxyethanol",
        "PHENOXYETHANOL",
        quantity(
            "exact", value=10.0, unit="percent",
            quantity_scope="supplier_material", raw_text="10%",
        ),
        identity="catalogue:phenoxyethanol",
    )).model_copy(update={
        "material_id": "preservative-booster",
        "trade_name": "Preservative Booster",
        "governing_document_id": "booster-document",
        "attached_document_ids": ["booster-document"],
        "finished_product_usage": quantity(
            "exact", value=1.0, unit="percent",
            quantity_scope="finished_product", preparation_stage="finished_product", raw_text="1%",
        ),
    })
    preserva.constituents[0].cas_number = "122-99-6"
    booster.constituents[0].cas_number = "122-99-6"

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[direct],
        materials=[preserva, booster],
    )

    assert prepared.formulation is not None
    assert len(prepared.formulation.ingredients) == 1
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration.concentration_type.value == "exact"
    assert concentration.value == pytest.approx(1.12)
    assert len(prepared.result.included_ingredients[0].contributions) == 3


def test_unknown_supplier_contribution_keeps_known_subtotal_qualified() -> None:
    direct = DirectIngredient(
        ingredient_id="direct-phenoxyethanol",
        source_document_id="finished-formula",
        verified_identity_group="catalogue:phenoxyethanol",
        ingredient=FormulationIngredientRequest(
            name="PHENOXYETHANOL",
            cas_number="122-99-6",
            concentration=FormulationConcentration(
                concentration_type="exact",
                value=0.3,
                unit="percent",
                basis=None,
                preparation_stage="finished_product",
            ),
        ),
    )
    blend = material(constituent(
        "unknown-phenoxyethanol",
        "PHENOXYETHANOL",
        quantity(
            "exact", value=90.0, unit="percent",
            quantity_scope="supplier_material", raw_text="90%",
        ),
        identity="catalogue:phenoxyethanol",
    )).model_copy(update={"finished_product_usage": None})
    blend.constituents[0].cas_number = "122-99-6"

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[direct],
        materials=[blend],
    )

    assert prepared.formulation is not None
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration.concentration_type.value == "lower_bound"
    assert concentration.lower_bound == pytest.approx(0.3)
    assert concentration.upper_bound is None
    assert any(issue.code == "material_usage_missing" for issue in prepared.result.issues)


def test_incomplete_supplier_disclosure_persists_partial_screening_input():
    blend = material(
        constituent(
            "preservative",
            "PHENOXYETHANOL",
            quantity(
                "range", lower=25.0, upper=50.0, unit="percent",
                quantity_scope="supplier_material", raw_text="25-50%",
            ),
            identity="catalogue:phenoxyethanol",
        ),
        complete=False,
    )
    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[],
        materials=[blend],
    )
    assert prepared.result.completeness.value == "partial"
    assert prepared.formulation is not None
    assert prepared.formulation.document_completeness.value == "partial_disclosure"
    assert any(issue.code == "incomplete_supplier_disclosure" for issue in prepared.result.issues)
    assert prepared.result.calculation_snapshot["issues"]


def test_missing_material_usage_is_unknown_not_zero():
    blend = material(
        constituent(
            "preservative",
            "PHENOXYETHANOL",
            quantity(
                "exact", value=100.0, unit="percent",
                quantity_scope="supplier_material", raw_text="100%",
            ),
            identity="catalogue:phenoxyethanol",
        ),
    ).model_copy(update={"finished_product_usage": None})
    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[],
        materials=[blend],
    )
    assert prepared.result.completeness.value == "partial"
    assert prepared.formulation is not None
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration.concentration_type.value == "unknown"
    assert any(issue.code == "material_usage_missing" for issue in prepared.result.issues)


def test_missing_direct_amount_is_coverage_until_a_rule_needs_it() -> None:
    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[DirectIngredient(
            ingredient_id="aqua",
            ingredient=FormulationIngredientRequest(name="AQUA", concentration=None),
            source_document_id="formula",
            verified_identity_group="catalogue:aqua",
        )],
        materials=[],
        source_document_ids=["formula"],
    )

    assert prepared.formulation is not None
    assert prepared.formulation.assembly_scope is not None
    assert prepared.formulation.assembly_scope.action_required_codes == []
    assert "constituent_concentration_missing" in (
        prepared.formulation.assembly_scope.coverage_limitation_codes
    )
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration.concentration_type.value == "unknown"


def test_duplicate_source_lineage_is_blocked_and_not_double_counted():
    blend = material(constituent(
        "a", "A",
        quantity("exact", value=100.0, unit="percent", quantity_scope="supplier_material"),
        identity="identity:a",
    ))
    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[],
        materials=[blend, blend],
    )
    assert prepared.result.completeness.value == "blocked"
    assert prepared.formulation is None
    assert any(issue.code == "duplicate_document" for issue in prepared.result.issues)


def test_impossible_aggregate_is_reported_without_crashing_mixed_upload() -> None:
    first = DirectIngredient(
        ingredient_id="formula-a:glycerin",
        source_document_id="formula-a.pdf",
        verified_identity_group="catalogue:glycerin",
        ingredient=FormulationIngredientRequest(
            name="GLYCERIN",
            cas_number="56-81-5",
            concentration=FormulationConcentration(
                concentration_type="exact", value=60, unit="percent", basis=None,
                preparation_stage="finished_product",
            ),
        ),
    )
    second = DirectIngredient(
        ingredient_id="formula-b:glycerin",
        source_document_id="formula-b.xlsx",
        verified_identity_group="catalogue:glycerin",
        ingredient=FormulationIngredientRequest(
            name="GLYCERIN",
            cas_number="56-81-5",
            concentration=FormulationConcentration(
                concentration_type="exact", value=50, unit="percent", basis=None,
                preparation_stage="finished_product",
            ),
        ),
    )
    valid = DirectIngredient(
        ingredient_id="formula-b:niacinamide",
        source_document_id="formula-b.xlsx",
        verified_identity_group="catalogue:niacinamide",
        ingredient=FormulationIngredientRequest(
            name="NIACINAMIDE",
            cas_number="98-92-0",
            concentration=FormulationConcentration(
                concentration_type="exact", value=4, unit="percent", basis=None,
                preparation_stage="finished_product",
            ),
        ),
    )

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[first, second, valid],
        materials=[],
        source_document_ids=["formula-a.pdf", "formula-b.xlsx"],
    )

    assert prepared.formulation is not None
    assert prepared.result.completeness.value == "partial"
    assert [item.display_name for item in prepared.result.included_ingredients] == ["NIACINAMIDE"]
    assert [item.name for item in prepared.formulation.ingredients] == ["NIACINAMIDE"]
    issue = next(
        item for item in prepared.result.issues
        if item.issue_id == "impossible_composition_total:aggregate:catalogue:glycerin"
    )
    assert issue.severity.value == "error"
    assert issue.blocking_for_calculation is False
    assert {item["name"] for item in prepared.result.excluded_items} == {"GLYCERIN"}


def test_unresolved_direct_identity_remains_visible_and_prevents_full_evaluation():
    direct = DirectIngredient(
        ingredient_id="direct-unknown",
        source_document_id="formulation-doc",
        ingredient=FormulationIngredientRequest(name="Mystery Extract"),
    )
    prepared = prepare_assembly(
        assembly_revision=0,
        direct_ingredients=[direct],
        materials=[],
    )
    assert prepared.result.completeness.value == "partial"
    assert prepared.formulation is not None
    assert prepared.formulation.ingredients[0].name == "Mystery Extract"
    assert prepared.result.excluded_items[0]["reason"] == "identity_unresolved"


@pytest.mark.parametrize(
    ("supplier_percentage", "expected_finished_percentage", "expected_finding"),
    [
        (5.0, 0.1, "restriction_within_limit"),
        (10.0, 0.2, "restriction_within_limit"),
        (12.5, 0.25, "restriction_exceeded"),
    ],
)
def test_calculated_trade_material_contribution_reaches_singapore_screening(
    supplier_percentage: float,
    expected_finished_percentage: float,
    expected_finding: str,
) -> None:
    """Prove the assembly boundary feeds the accepted Part II rule unchanged."""
    blend = material(
        MaterialConstituent(
            constituent_id="tosylchloramide",
            submitted_name="Tosylchloramide sodium",
            cas_number="127-65-1",
            composition_quantity=quantity(
                "exact",
                value=supplier_percentage,
                unit="percent",
                quantity_scope="supplier_material",
                raw_text=f"{supplier_percentage:g}%",
            ),
            verified_identity_group="singapore:substance-sg-third-schedule-ii-5",
        ),
        MaterialConstituent(
            constituent_id="carrier",
            submitted_name="AQUA",
            cas_number="7732-18-5",
            composition_quantity=quantity(
                "exact",
                value=100 - supplier_percentage,
                unit="percent",
                quantity_scope="supplier_material",
                raw_text=f"{100 - supplier_percentage:g}%",
            ),
            verified_identity_group="source:aqua",
        ),
    )

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[],
        materials=[blend],
        source_document_ids=["doc-1"],
    )

    assert prepared.result.completeness.value == "complete"
    assert prepared.formulation is not None
    prepared_ingredient = next(
        ingredient for ingredient in prepared.formulation.ingredients
        if ingredient.name == "Tosylchloramide sodium"
    )
    concentration = prepared_ingredient.concentration
    assert concentration is not None
    assert concentration.value == pytest.approx(expected_finished_percentage)

    result = screen_formulation(load_accepted_store(ROOT), prepared.formulation)
    ingredient_result = next(
        item for item in result.ingredient_results
        if item.submitted_ingredient.name == "Tosylchloramide sodium"
    )
    assert ingredient_result.primary_finding.value == expected_finding
    assert {
        evaluation.evidence.reference_number
        for evaluation in ingredient_result.rule_evaluations
            if evaluation.evidence.regulatory_section == "Third Schedule Part II"
    } == {"5"}


@pytest.mark.parametrize(
    ("supplier_lower", "supplier_upper", "expected_lower", "expected_upper", "expected_finding"),
    [
        (2.5, 5.0, 0.05, 0.1, "restriction_within_limit"),
        (5.0, 15.0, 0.1, 0.3, "professional_review_required"),
        (10.5, 20.0, 0.21, 0.4, "restriction_exceeded"),
    ],
)
def test_calculated_supplier_ranges_are_screened_conservatively(
    supplier_lower: float,
    supplier_upper: float,
    expected_lower: float,
    expected_upper: float,
    expected_finding: str,
) -> None:
    blend = material(MaterialConstituent(
        constituent_id="tosylchloramide-range",
        submitted_name="Tosylchloramide sodium",
        cas_number="127-65-1",
        composition_quantity=quantity(
            "range",
            lower=supplier_lower,
            upper=supplier_upper,
            lower_inclusive=True,
            upper_inclusive=True,
            unit="percent",
            quantity_scope="supplier_material",
            raw_text=f"{supplier_lower:g}-{supplier_upper:g}%",
        ),
        verified_identity_group="singapore:substance-sg-third-schedule-ii-5",
    ))

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[],
        materials=[blend],
        source_document_ids=["doc-1"],
    )

    assert prepared.formulation is not None
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration is not None
    assert concentration.lower_bound == pytest.approx(expected_lower)
    assert concentration.upper_bound == pytest.approx(expected_upper)
    result = screen_formulation(load_accepted_store(ROOT), prepared.formulation)
    assert result.ingredient_results[0].primary_finding.value == expected_finding


def test_confirmed_exceedance_survives_partial_supplier_disclosure() -> None:
    blend = material(
        MaterialConstituent(
            constituent_id="tosylchloramide-partial",
            submitted_name="Tosylchloramide sodium",
            cas_number="127-65-1",
            composition_quantity=quantity(
                "exact",
                value=12.5,
                unit="percent",
                quantity_scope="supplier_material",
                raw_text="12.5%",
            ),
            verified_identity_group="singapore:substance-sg-third-schedule-ii-5",
        ),
        complete=False,
    )
    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[],
        materials=[blend],
        source_document_ids=["supplier-sds-page-2"],
    )

    assert prepared.result.completeness.value == "partial"
    assert prepared.formulation is not None
    result = screen_formulation(load_accepted_store(ROOT), prepared.formulation)
    ingredient_result = result.ingredient_results[0]
    assert ingredient_result.primary_finding.value == "restriction_exceeded"
    assert ingredient_result.screening_disposition.value == "fully_evaluated"
    assert "assembly_incomplete" not in {
        issue.code for issue in ingredient_result.review_issues
    }
    assert result.formulation.assembly_scope.completeness == "partial"


def test_regulatory_engine_evaluates_direct_and_supplier_aggregate() -> None:
    identity = "singapore:substance-sg-third-schedule-ii-5"
    direct = DirectIngredient(
        ingredient_id="direct-tosylchloramide",
        source_document_id="finished-formula",
        verified_identity_group=identity,
        ingredient=FormulationIngredientRequest(
            name="Tosylchloramide sodium",
            cas_number="127-65-1",
            concentration=FormulationConcentration(
                concentration_type="exact",
                value=0.1,
                unit="percent",
                basis=None,
                preparation_stage="finished_product",
            ),
        ),
    )
    blend = material(MaterialConstituent(
        constituent_id="blend-tosylchloramide",
        submitted_name="Tosylchloramide sodium",
        cas_number="127-65-1",
        composition_quantity=quantity(
            "exact", value=12.5, unit="percent",
            quantity_scope="supplier_material", raw_text="12.5%",
        ),
        verified_identity_group=identity,
    )).model_copy(update={
        "finished_product_usage": quantity(
            "exact", value=1.0, unit="percent",
            quantity_scope="finished_product", preparation_stage="finished_product", raw_text="1%",
        ),
    })

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[direct],
        materials=[blend],
    )

    assert prepared.formulation is not None
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration.value == pytest.approx(0.225)
    response = screen_formulation(load_accepted_store(ROOT), prepared.formulation)
    result = response.ingredient_results[0]
    assert result.submitted_ingredient.concentration.value == pytest.approx(0.225)
    assert result.primary_finding.value == "restriction_exceeded"

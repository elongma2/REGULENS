from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from backend.app.models.document_intake import (
    AssemblyCompleteness,
    AssemblyIssue,
    AssemblyIssueScope,
    AssemblyIssueSeverity,
    AssemblyResult,
    CalculatedContribution,
    CompositionQuantity,
    CompositionQuantityKind,
    DirectIngredient,
    PreparedAssembly,
    SupplierMaterial,
)
from backend.app.models.formulation import (
    ConcentrationBasis,
    ConcentrationUnit,
    DocumentCompleteness,
    FormulationConcentration,
    FormulationAssemblyScope,
    FormulationIngredientRequest,
    FormulationRequest,
    PreparationStage,
    ProductApplicabilityFacts,
    SourceDocumentType,
)
from backend.app.models.screening import ConcentrationType
from backend.app.services.material_calculation import (
    aggregate_contributions,
    calculate_material_contributions,
)


_FORMULATION_TO_COMPOSITION_KIND = {
    ConcentrationType.EXACT: CompositionQuantityKind.EXACT,
    ConcentrationType.RANGE: CompositionQuantityKind.RANGE,
    ConcentrationType.UPPER_BOUND: CompositionQuantityKind.UPPER_BOUND,
    ConcentrationType.LOWER_BOUND: CompositionQuantityKind.LOWER_BOUND,
    ConcentrationType.APPROXIMATE: CompositionQuantityKind.APPROXIMATE,
    ConcentrationType.UNKNOWN: CompositionQuantityKind.UNKNOWN,
}

_COMPOSITION_TO_FORMULATION_KIND = {
    CompositionQuantityKind.EXACT: ConcentrationType.EXACT,
    CompositionQuantityKind.RANGE: ConcentrationType.RANGE,
    CompositionQuantityKind.UPPER_BOUND: ConcentrationType.UPPER_BOUND,
    CompositionQuantityKind.LOWER_BOUND: ConcentrationType.LOWER_BOUND,
    CompositionQuantityKind.APPROXIMATE: ConcentrationType.APPROXIMATE,
    CompositionQuantityKind.UNKNOWN: ConcentrationType.UNKNOWN,
}


def _direct_quantity(concentration: FormulationConcentration | None) -> CompositionQuantity:
    if concentration is None:
        return CompositionQuantity(
            kind=CompositionQuantityKind.UNKNOWN,
            unit="percent",
            preparation_stage="finished_product",
            quantity_scope="finished_product",
            raw_text="Not supplied",
        )
    return CompositionQuantity(
        kind=_FORMULATION_TO_COMPOSITION_KIND[concentration.concentration_type],
        value=concentration.value,
        lower=concentration.lower_bound,
        upper=concentration.upper_bound,
        lower_inclusive=concentration.lower_inclusive,
        upper_inclusive=concentration.upper_inclusive,
        unit=concentration.unit.value if concentration.unit else None,
        basis=concentration.basis.value if concentration.basis else None,
        preparation_stage=concentration.preparation_stage.value if concentration.preparation_stage else None,
        quantity_scope="finished_product",
        raw_text=concentration.original_text,
        approximate=concentration.concentration_type == ConcentrationType.APPROXIMATE,
    )


def _canonical_concentration(quantity: CompositionQuantity) -> FormulationConcentration | None:
    if quantity.kind not in _COMPOSITION_TO_FORMULATION_KIND:
        return None
    unit = None
    if quantity.unit:
        try:
            unit = ConcentrationUnit(quantity.unit)
        except ValueError:
            return None
    basis = None
    if quantity.basis:
        try:
            basis = ConcentrationBasis(quantity.basis)
        except ValueError:
            return None
    stage = None
    if quantity.preparation_stage:
        try:
            stage = PreparationStage(quantity.preparation_stage)
        except ValueError:
            return None
    return FormulationConcentration(
        concentration_type=_COMPOSITION_TO_FORMULATION_KIND[quantity.kind],
        value=quantity.value,
        lower_bound=quantity.lower,
        upper_bound=quantity.upper,
        lower_inclusive=quantity.lower_inclusive,
        upper_inclusive=quantity.upper_inclusive,
        # The calculation expression belongs to the contribution snapshot/evidence,
        # not to the canonical value evaluated by the regulatory engine.
        original_text=None,
        unit=unit,
        basis=basis,
        preparation_stage=stage,
    )


def _invalid_finished_product_percentage(quantity: CompositionQuantity) -> bool:
    if quantity.unit != "percent":
        return False
    values = [value for value in (quantity.value, quantity.lower, quantity.upper) if value is not None]
    return any(value < 0 or value > 100 for value in values)


def _direct_contribution(row: DirectIngredient) -> CalculatedContribution | None:
    if not row.verified_identity_group:
        return None
    quantity = _direct_quantity(row.ingredient.concentration)
    return CalculatedContribution(
        contribution_id=f"direct:{row.ingredient_id}:document:{row.source_document_id}",
        source_type="direct_ingredient",
        source_direct_ingredient_id=row.ingredient_id,
        governing_document_id=row.source_document_id,
        verified_identity_group=row.verified_identity_group,
        display_name=row.ingredient.name,
        cas_number=row.ingredient.cas_number,
        regulated_functions=row.ingredient.regulated_functions,
        finished_product_quantity=quantity,
        calculation_formula="Direct finished-product ingredient",
        source_evidence=row.source_evidence,
    )


def _unknown_material_contribution(
    material: SupplierMaterial,
    constituent_index: int,
) -> CalculatedContribution | None:
    constituent = material.constituents[constituent_index]
    if not constituent.verified_identity_group:
        return None
    document_id = material.governing_document_id or (
        material.attached_document_ids[0] if material.attached_document_ids else "unassociated"
    )
    return CalculatedContribution(
        contribution_id=(
            f"material:{material.material_id}:constituent:{constituent.constituent_id}:"
            f"document:{document_id}:withheld"
        ),
        source_type="material_constituent",
        source_material_id=material.material_id,
        source_constituent_id=constituent.constituent_id,
        governing_document_id=document_id,
        verified_identity_group=constituent.verified_identity_group,
        display_name=constituent.submitted_name,
        cas_number=constituent.cas_number,
        regulated_functions=constituent.regulated_functions,
        composition_quantity=constituent.composition_quantity,
        material_usage=material.finished_product_usage,
        finished_product_quantity=CompositionQuantity(
            kind=CompositionQuantityKind.UNKNOWN,
            unit="percent",
            basis=constituent.composition_quantity.basis if constituent.composition_quantity else None,
            preparation_stage="finished_product",
            quantity_scope="finished_product",
            raw_text="Calculation withheld because required material information is unresolved",
        ),
        calculation_formula="Withheld: material usage, association or compatible composition is unresolved",
        source_evidence=constituent.source_evidence,
    )


def _deduplicate_contributions(
    contributions: Iterable[CalculatedContribution],
) -> tuple[list[CalculatedContribution], list[AssemblyIssue]]:
    values = list(contributions)
    counts = Counter(item.contribution_id for item in values)
    duplicates = {key for key, count in counts.items() if count > 1}
    if not duplicates:
        return values, []
    issues = [AssemblyIssue(
        issue_id=f"duplicate_document:{key}",
        code="duplicate_document",
        severity=AssemblyIssueSeverity.ERROR,
        scope=AssemblyIssueScope.CALCULATION,
        message="The same source lineage would contribute more than once.",
        reviewer_action="Remove the duplicate document or material association before calculation.",
        blocking_for_calculation=True,
        document_ids=sorted({item.governing_document_id for item in values if item.contribution_id == key}),
        material_ids=sorted({item.source_material_id for item in values if item.contribution_id == key and item.source_material_id}),
        constituent_ids=sorted({item.source_constituent_id for item in values if item.contribution_id == key and item.source_constituent_id}),
    ) for key in sorted(duplicates)]
    return [item for item in values if item.contribution_id not in duplicates], issues


def prepare_assembly(
    *,
    assembly_revision: int,
    direct_ingredients: list[DirectIngredient],
    materials: list[SupplierMaterial],
    formulation_id: str | None = None,
    formulation_name: str | None = None,
    product_context: str | None = None,
    product_applicability: ProductApplicabilityFacts | None = None,
    source_filename: str | None = None,
    source_document_ids: list[str] | None = None,
    source_document_metadata: dict[str, dict[str, str | None]] | None = None,
) -> PreparedAssembly:
    issues: list[AssemblyIssue] = []
    contributions: list[CalculatedContribution] = []
    excluded_items: list[dict[str, Any]] = []

    for direct in direct_ingredients:
        direct_contribution = _direct_contribution(direct)
        if direct_contribution:
            contributions.append(direct_contribution)
            if direct.ingredient.concentration is None:
                issues.append(AssemblyIssue(
                    issue_id=f"constituent_concentration_missing:direct:{direct.ingredient_id}",
                    code="constituent_concentration_missing",
                    severity=AssemblyIssueSeverity.WARNING,
                    scope=AssemblyIssueScope.CONSTITUENT,
                    message=f"Finished-product concentration is missing for {direct.ingredient.name}.",
                    reviewer_action=(
                        "Regulens will preserve the ingredient with an unknown amount. "
                        "A concentration will be requested only if an applicable rule needs it."
                    ),
                    blocking_for_calculation=False,
                    constituent_ids=[direct.ingredient_id],
                    document_ids=[direct.source_document_id],
                    evidence=direct.source_evidence,
                ))
        else:
            excluded_items.append({
                "type": "direct_ingredient",
                "id": direct.ingredient_id,
                "name": direct.ingredient.name,
                "reason": "identity_unresolved",
            })
            issues.append(AssemblyIssue(
                issue_id=f"constituent_identity_unresolved:direct:{direct.ingredient_id}",
                code="constituent_identity_unresolved",
                severity=AssemblyIssueSeverity.REVIEW_REQUIRED,
                scope=AssemblyIssueScope.CONSTITUENT,
                message=f"The identity of {direct.ingredient.name} is unresolved.",
                reviewer_action="Confirm the ingredient identity before aggregation; identity-based screening remains incomplete.",
                blocking_for_calculation=True,
                constituent_ids=[direct.ingredient_id],
                document_ids=[direct.source_document_id],
                evidence=direct.source_evidence,
            ))

    normalized_materials: list[SupplierMaterial] = []
    for material in materials:
        normalized, calculated, material_issues = calculate_material_contributions(material)
        normalized_materials.append(normalized)
        issues.extend(material_issues)
        contributions.extend(calculated)
        calculated_constituents = {item.source_constituent_id for item in calculated}
        for index, constituent in enumerate(normalized.constituents):
            if constituent.constituent_id in calculated_constituents:
                continue
            fallback = _unknown_material_contribution(normalized, index)
            if fallback:
                contributions.append(fallback)
            else:
                excluded_items.append({
                    "type": "material_constituent",
                    "material_id": normalized.material_id,
                    "id": constituent.constituent_id,
                    "name": constituent.submitted_name,
                    "reason": "identity_unresolved",
                })

    contributions, duplicate_issues = _deduplicate_contributions(contributions)
    issues.extend(duplicate_issues)
    aggregates, aggregation_issues = aggregate_contributions(contributions)
    issues.extend(aggregation_issues)

    canonical_ingredients: list[FormulationIngredientRequest] = []
    screenable_aggregates = []
    for aggregate in aggregates:
        if _invalid_finished_product_percentage(aggregate.aggregate_quantity):
            issues.append(AssemblyIssue(
                issue_id=f"impossible_composition_total:aggregate:{aggregate.verified_identity_group}",
                code="impossible_composition_total",
                severity=AssemblyIssueSeverity.ERROR,
                scope=AssemblyIssueScope.CALCULATION,
                message=(
                    f"The combined finished-product amount for {aggregate.display_name} is outside "
                    "the possible 0% to 100% range."
                ),
                reviewer_action=(
                    "Check whether more than one finished formulation or duplicate source was "
                    "uploaded, then correct the affected amount or document association."
                ),
                # This aggregate cannot be calculated safely, but unrelated valid
                # ingredients may still proceed to explicitly partial screening.
                blocking_for_calculation=False,
                document_ids=sorted({item.governing_document_id for item in aggregate.contributions}),
                material_ids=sorted({
                    item.source_material_id for item in aggregate.contributions
                    if item.source_material_id
                }),
                constituent_ids=sorted({
                    item.source_constituent_id for item in aggregate.contributions
                    if item.source_constituent_id
                }),
            ))
            excluded_items.append({
                "type": "aggregated_ingredient",
                "id": aggregate.verified_identity_group,
                "name": aggregate.display_name,
                "reason": "impossible_composition_total",
            })
            continue
        canonical_ingredients.append(FormulationIngredientRequest(
            name=aggregate.display_name,
            cas_number=aggregate.cas_number,
            concentration=_canonical_concentration(aggregate.aggregate_quantity),
            regulated_functions=aggregate.regulated_functions,
        ))
        screenable_aggregates.append(aggregate)

    # Preserve unresolved direct rows for the existing conservative resolver. They
    # are not aggregated and their AssemblyIssue prevents full-evaluation wording.
    for direct in direct_ingredients:
        if direct.verified_identity_group:
            continue
        canonical_ingredients.append(direct.ingredient)

    if not canonical_ingredients:
        # FormulationRequest deliberately requires at least one ingredient. A
        # completely blocked assembly cannot be prepared for screening.
        issues.append(AssemblyIssue(
            issue_id="calculation_withheld:assembly:no-screenable-ingredients",
            code="calculation_withheld",
            severity=AssemblyIssueSeverity.ERROR,
            scope=AssemblyIssueScope.ASSEMBLY,
            message="No ingredient can be passed safely to regulatory screening.",
            reviewer_action="Resolve at least one material association and ingredient identity.",
            blocking_for_calculation=True,
        ))

    blocking = any(issue.blocking_for_calculation and issue.severity == AssemblyIssueSeverity.ERROR for issue in issues)
    incomplete = any(issue.blocking_for_full_evaluation for issue in issues)
    completeness = (
        AssemblyCompleteness.BLOCKED if blocking
        else AssemblyCompleteness.PARTIAL if incomplete
        else AssemblyCompleteness.COMPLETE
    )
    result = AssemblyResult(
        assembly_revision=assembly_revision,
        completeness=completeness,
        included_ingredients=screenable_aggregates,
        unresolved_raw_materials=sorted({
            material_id for issue in issues if issue.code == "unresolved_raw_material"
            for material_id in issue.material_ids
        }),
        incomplete_disclosures=sorted({
            material_id for issue in issues if issue.code == "incomplete_supplier_disclosure"
            for material_id in issue.material_ids
        }),
        unresolved_associations=sorted({
            material_id for issue in issues if issue.code == "document_association_unconfirmed"
            for material_id in issue.material_ids
        }),
        excluded_items=excluded_items,
        issues=issues,
        evaluated_scope={
            "direct_ingredient_count": len(direct_ingredients),
            "material_count": len(materials),
            "contribution_count": len(contributions),
            "aggregated_ingredient_count": len(aggregates),
        },
        calculation_snapshot={
            "algorithm_version": "trade-material-calculation-v1",
            "assembly_revision": assembly_revision,
            "source_documents": {
                **(source_document_metadata or {}),
                **({
                    document_id: {
                        "original_filename": source_filename,
                        "supplier_name": None,
                        "trade_name": None,
                        "product_code": None,
                    }
                    for document_id in (source_document_ids or [])
                    if document_id.startswith("primary:")
                }),
            },
            "materials": [material.model_dump(mode="json") for material in normalized_materials],
            "contributions": [item.model_dump(mode="json") for item in contributions],
            "aggregates": [item.model_dump(mode="json") for item in aggregates],
            "issues": [item.model_dump(mode="json") for item in issues],
        },
    )

    formulation = FormulationRequest(
        formulation_id=formulation_id,
        formulation_name=formulation_name,
        product_context=product_context,
        product_applicability=product_applicability or ProductApplicabilityFacts(),
        source_document_type=SourceDocumentType.FORMULATION,
        document_completeness=(
            DocumentCompleteness.FULL_FORMULATION
            if completeness == AssemblyCompleteness.COMPLETE
            else DocumentCompleteness.PARTIAL_DISCLOSURE
        ),
        source_filename=source_filename,
        assembly_scope=FormulationAssemblyScope(
            completeness=completeness.value,
            issue_codes=sorted({issue.code for issue in issues}),
            action_required_codes=sorted({
                issue.code for issue in issues
                if issue.severity != AssemblyIssueSeverity.WARNING
            }),
            coverage_limitation_codes=sorted({
                issue.code for issue in issues
                if issue.severity == AssemblyIssueSeverity.WARNING
            }),
            unresolved_material_ids=result.unresolved_raw_materials,
            incomplete_disclosure_material_ids=result.incomplete_disclosures,
            unresolved_association_ids=result.unresolved_associations,
            source_document_ids=sorted(set(source_document_ids or [
                document_id
                for material in normalized_materials
                for document_id in material.attached_document_ids
            ])),
        ),
        assembly_calculation_snapshot=result.calculation_snapshot,
        ingredients=canonical_ingredients,
    ) if canonical_ingredients else None
    return PreparedAssembly(result=result, formulation=formulation)

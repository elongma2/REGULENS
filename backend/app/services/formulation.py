from __future__ import annotations

from collections import Counter

from backend.app.models.formulation import (
    FINDING_SUMMARY_FIELDS,
    DatasetIdentity,
    FormulationMetadata,
    FormulationRequest,
    FormulationScreeningResponse,
    FormulationSummary,
    IngredientScreeningResponse,
    source_snapshot_from_record,
)
from backend.app.models.screening import ConcentrationInput, IngredientInput
from backend.app.services.compliance import screen_ingredient
from backend.app.services.ingredient_catalog import IDENTITY_SOURCE_NAME, IngredientCatalog
from backend.app.services.loader import RegulatoryStore
from backend.app.models.identity_catalogue import IdentityCatalogueDataset, IdentityLinkageDataset
from backend.app.services.parsing import validate_formulation_request


def _runtime_ingredient(ingredient) -> IngredientInput:
    concentration = ingredient.concentration
    runtime_concentration = None
    if concentration is not None:
        runtime_concentration = ConcentrationInput(
            value=concentration.value,
            unit=concentration.unit.value,
            basis=concentration.basis.value if concentration.basis is not None else None,
            preparation_stage=concentration.preparation_stage.value,
        )
    return IngredientInput(
        name=ingredient.name,
        cas_number=ingredient.cas_number,
        concentration=runtime_concentration,
        regulated_functions=ingredient.regulated_functions,
    )


def screen_formulation(
    store: RegulatoryStore,
    request: FormulationRequest,
    ingredient_catalog: IngredientCatalog | None = None,
    catalogue_error: str | None = None,
) -> FormulationScreeningResponse:
    duplicate_groups = validate_formulation_request(request, store)
    results = [
        screen_ingredient(
            store,
            _runtime_ingredient(ingredient),
            request.product_context,
            request.product_applicability.model_dump(),
            ingredient_catalog=ingredient_catalog,
            catalogue_error=catalogue_error,
        )
        for ingredient in request.ingredients
    ]
    primary_counts = Counter(result.primary_finding for result in results)
    summary_values = {
        field: primary_counts[finding]
        for finding, field in FINDING_SUMMARY_FIELDS.items()
    }
    summary = FormulationSummary(
        ingredients_submitted=len(results),
        **summary_values,
        total_requiring_review=sum(result.review_required for result in results),
        total_unresolved_identities=sum(
            result.primary_finding.value == "identity_unresolved" for result in results
        ),
        duplicate_row_groups=duplicate_groups,
    )
    ingredient_results = [
        IngredientScreeningResponse(
            submitted_row_number=row_number,
            **result.model_dump(),
        )
        for row_number, result in enumerate(results, start=1)
    ]
    return FormulationScreeningResponse(
        formulation=FormulationMetadata(
            formulation_id=request.formulation_id,
            formulation_name=request.formulation_name,
            product_context=request.product_context,
            product_applicability=request.product_applicability,
        ),
        dataset=DatasetIdentity(
            dataset_version=store.dataset_version,
            accepted_baseline_sha256=store.baseline_manifest_hash,
            sources=[source_snapshot_from_record(record) for record in store.source_snapshots],
            identity_catalogue=IdentityCatalogueDataset(
                available=ingredient_catalog is not None,
                dataset_version=(ingredient_catalog.dataset_version if ingredient_catalog else None),
                accepted_baseline_sha256=(
                    ingredient_catalog.baseline_manifest_hash if ingredient_catalog else None
                ),
                source_name=(IDENTITY_SOURCE_NAME if ingredient_catalog else None),
                source_role=(ingredient_catalog.source_document["source_role"] if ingredient_catalog else None),
                ingredient_count=(ingredient_catalog.ingredient_count if ingredient_catalog else None),
                error=(catalogue_error if ingredient_catalog is None else None),
            ),
            identity_linkage=IdentityLinkageDataset(
                available=False,
                screened_scope=[],
                error=None,
            ),
        ),
        summary=summary,
        ingredient_results=ingredient_results,
    )

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
from backend.app.services.resolver import resolve_ingredient
from backend.app.services.ingredient_catalog import IDENTITY_SOURCE_NAME, IngredientCatalog
from backend.app.services.ingredient_linkage import IngredientLinkageStore
from backend.app.services.loader import RegulatoryStore
from backend.app.models.identity_catalogue import IdentityCatalogueDataset, IdentityLinkageDataset
from backend.app.services.parsing import validate_formulation_request


def _runtime_ingredient(ingredient) -> IngredientInput:
    concentration = ingredient.concentration
    runtime_concentration = None
    if concentration is not None:
        runtime_concentration = ConcentrationInput(
            concentration_type=concentration.concentration_type,
            value=concentration.value,
            lower_bound=concentration.lower_bound,
            upper_bound=concentration.upper_bound,
            lower_inclusive=concentration.lower_inclusive,
            upper_inclusive=concentration.upper_inclusive,
            original_text=concentration.original_text,
            unit=concentration.unit.value if concentration.unit is not None else None,
            basis=concentration.basis.value if concentration.basis is not None else None,
            preparation_stage=(
                concentration.preparation_stage.value
                if concentration.preparation_stage is not None
                else None
            ),
        )
    return IngredientInput(
        name=ingredient.name,
        cas_number=ingredient.cas_number,
        concentration=runtime_concentration,
        regulated_functions=ingredient.regulated_functions,
    )


def _combined_contexts(store, ingredients, identities) -> dict[str, dict]:
    requirements: dict[str, dict] = {}
    for identity in identities:
        ids = identity.resolved_singapore_substance_ids or (
            [identity.resolved_singapore_substance_id] if identity.resolved_singapore_substance_id else []
        )
        for substance_id in ids:
            for rule in store.rules_by_substance_id.get(substance_id, ()):
                for requirement in rule.get("combined_limit_requirements", []):
                    requirements[requirement["group_key"]] = requirement

    output: dict[str, dict] = {}
    for group_key, requirement in requirements.items():
        expected = set(requirement.get("constituent_references", []))
        contributions: dict[str, list] = {reference: [] for reference in expected}
        for ingredient, identity in zip(ingredients, identities, strict=True):
            exact_refs = {
                candidate.reference_number
                for candidate in identity.singapore_candidates
                if any(method in {"exact_name", "exact_ci", "accepted_identity_linkage"} for method in candidate.match_methods)
            }
            for reference in expected & exact_refs:
                contributions[reference].append(ingredient.concentration)
        missing = sorted(reference for reference, values in contributions.items() if not values)
        maximum = requirement["maximum"]
        values: list[float] = []
        compatible = not missing
        for concentrations in contributions.values():
            for concentration in concentrations:
                if (
                    concentration is None
                    or concentration.concentration_type.value != "exact"
                    or concentration.value is None
                    or concentration.unit != maximum["unit"]
                    or concentration.basis != maximum.get("basis")
                    or concentration.preparation_stage != maximum["preparation_stage"]
                ):
                    compatible = False
                else:
                    values.append(concentration.value)
        output[group_key] = {
            "status": "complete" if compatible else "incomplete",
            "total": sum(values) if compatible else None,
            "missing_references": missing,
            "constituent_references": sorted(expected),
        }
    return output


def screen_formulation(
    store: RegulatoryStore,
    request: FormulationRequest,
    ingredient_catalog: IngredientCatalog | None = None,
    linkage_store: IngredientLinkageStore | None = None,
    linkage_error: str | None = None,
    catalogue_error: str | None = None,
) -> FormulationScreeningResponse:
    linkage_active = bool(
        linkage_store is not None
        and linkage_store.singapore_regulatory_baseline == store.dataset_version
        and set(linkage_store.screened_scope) == {
            "Third Schedule Part I", "Third Schedule Part II", "Third Schedule Part III",
            "Third Schedule Part IV", "Third Schedule Part V",
        }
    )
    duplicate_groups = validate_formulation_request(request, store)
    runtime_ingredients = [_runtime_ingredient(ingredient) for ingredient in request.ingredients]
    identities = [
        resolve_ingredient(
            store,
            ingredient.name,
            ingredient.cas_number,
            ingredient_catalog=ingredient_catalog,
            linkage_store=linkage_store,
            catalogue_error=catalogue_error,
        )
        for ingredient in runtime_ingredients
    ]
    combined_contexts = _combined_contexts(store, runtime_ingredients, identities)
    results = [
        screen_ingredient(
            store,
            ingredient,
            request.product_context,
            request.product_applicability.model_dump(),
            ingredient_catalog=ingredient_catalog,
            linkage_store=linkage_store,
            catalogue_error=catalogue_error,
            identity_resolution=identity,
            combined_contexts=combined_contexts,
        )
        for ingredient, identity in zip(runtime_ingredients, identities, strict=True)
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
    response = FormulationScreeningResponse(
        formulation=FormulationMetadata(
            formulation_id=request.formulation_id,
            formulation_name=request.formulation_name,
            product_context=request.product_context,
            product_applicability=request.product_applicability,
            source_document_type=request.source_document_type,
            document_completeness=request.document_completeness,
            source_filename=request.source_filename,
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
                available=linkage_active,
                dataset_version=(linkage_store.dataset_version if linkage_active else None),
                accepted_baseline_sha256=(linkage_store.baseline_manifest_hash if linkage_active else None),
                identity_dataset_version=(linkage_store.identity_dataset_version if linkage_active else None),
                singapore_regulatory_baseline=(linkage_store.singapore_regulatory_baseline if linkage_active else None),
                screened_scope=(list(linkage_store.screened_scope) if linkage_active else []),
                accepted_records=(linkage_store.counts["accepted_records"] if linkage_active else None),
                linked=(linkage_store.counts["linked"] if linkage_active else None),
                verified_not_represented=(linkage_store.counts["verified_not_represented"] if linkage_active else None),
                unresolved=(linkage_store.counts["unresolved"] if linkage_active else None),
                error=(linkage_error or ("Accepted identity linkage is not bound to the active Parts I-V baseline." if linkage_store is not None and not linkage_active else None)),
            ),
        ),
        summary=summary,
        ingredient_results=ingredient_results,
    )
    return response

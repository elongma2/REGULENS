from __future__ import annotations

from collections import defaultdict
from typing import Hashable

from data_pipeline.scripts.normalize import conservative_text

from backend.app.models.formulation import FormulationIngredientRequest, FormulationRequest
from backend.app.services.loader import RegulatoryStore


class UnsupportedProductContextError(ValueError):
    """Raised when a formulation context is not in the accepted source-backed index."""


def validate_product_context(request: FormulationRequest, store: RegulatoryStore) -> None:
    if request.product_context is None:
        return
    key = conservative_text(request.product_context)
    if key not in store.source_backed_contexts:
        raise UnsupportedProductContextError(
            "Product context must exactly match an accepted source-backed context"
        )


def _ingredient_signature(ingredient: FormulationIngredientRequest) -> tuple[Hashable, ...]:
    concentration = ingredient.concentration
    concentration_signature: tuple[Hashable, ...] | None = None
    if concentration is not None:
        concentration_signature = (
            concentration.concentration_type.value,
            concentration.value,
            concentration.lower_bound,
            concentration.upper_bound,
            concentration.lower_inclusive,
            concentration.upper_inclusive,
            concentration.original_text,
            concentration.unit.value if concentration.unit is not None else None,
            concentration.basis.value if concentration.basis is not None else None,
            concentration.preparation_stage.value
            if concentration.preparation_stage is not None
            else None,
        )
    return (
        conservative_text(ingredient.name),
        ingredient.cas_number,
        concentration_signature,
    )


def find_duplicate_row_groups(request: FormulationRequest) -> list[list[int]]:
    rows_by_signature: dict[tuple[Hashable, ...], list[int]] = defaultdict(list)
    for row_number, ingredient in enumerate(request.ingredients, start=1):
        rows_by_signature[_ingredient_signature(ingredient)].append(row_number)
    return [rows for rows in rows_by_signature.values() if len(rows) > 1]


def validate_formulation_request(
    request: FormulationRequest, store: RegulatoryStore
) -> list[list[int]]:
    validate_product_context(request, store)
    return find_duplicate_row_groups(request)

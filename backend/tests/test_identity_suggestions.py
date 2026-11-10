from __future__ import annotations

from backend.app.models.document_intake import (
    FormulationAssemblyState,
    MaterialConstituent,
    SupplierMaterial,
)
from backend.app.models.screening import IdentitySuggestion, IdentitySuggestionStatus
from backend.app.services.identity_suggestions import add_pending_identity_suggestions
from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog


class StubSuggestionProvider:
    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def suggest(self, names, *, catalogue, formulation_names):
        self.calls += 1
        aqua = catalogue.find_exact_name("AQUA")
        assert aqua is not None
        return {
            "Water": IdentitySuggestion(
                target_id="placeholder",
                original_name="Water",
                canonical_name=aqua["canonical_name"],
                catalogue_ingredient_id=aqua["ingredient_id"],
                explanation="Water is the common-language name for AQUA.",
                model=self.model,
            ),
        }


def _state(suggestion: IdentitySuggestion | None = None) -> FormulationAssemblyState:
    return FormulationAssemblyState(materials=[SupplierMaterial(
        material_id="material-1",
        trade_name="Supplier Blend",
        constituents=[MaterialConstituent(
            constituent_id="water-row",
            submitted_name="Water",
            identity_suggestion=suggestion,
        )],
    )])


def test_unresolved_supplier_name_receives_pending_review_suggestion() -> None:
    provider = StubSuggestionProvider()
    updated = add_pending_identity_suggestions(
        _state(),
        catalogue=load_accepted_ingredient_catalog(),
        provider=provider,
    )

    suggestion = updated.materials[0].constituents[0].identity_suggestion
    assert provider.calls == 1
    assert suggestion is not None
    assert suggestion.target_id == "water-row"
    assert suggestion.canonical_name == "AQUA"
    assert suggestion.status == IdentitySuggestionStatus.PENDING


def test_rejected_supplier_name_is_not_suggested_again() -> None:
    provider = StubSuggestionProvider()
    rejected = IdentitySuggestion(
        target_id="water-row",
        original_name="Water",
        canonical_name="AQUA",
        catalogue_ingredient_id="eu-2025-1175-entry-00001",
        explanation="Reviewer-visible proposal.",
        model="test-model",
        status=IdentitySuggestionStatus.REJECTED,
    )

    updated = add_pending_identity_suggestions(
        _state(rejected),
        catalogue=load_accepted_ingredient_catalog(),
        provider=provider,
    )

    assert provider.calls == 0
    assert updated.materials[0].constituents[0].identity_suggestion == rejected

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.models.agent import (
    AgentConfidence,
    AgentFieldProvenance,
    AgentIngredientRow,
    AgentSessionState,
    AgentSessionView,
)
from backend.app.models.document_intake import (
    CompositionLegend,
    CompositionLegendEntry,
    CompositionQuantity,
    ConfirmationStatus,
    DisclosureStatus,
    DirectIngredient,
    DocumentClassification,
    DocumentExtraction,
    DocumentRole,
    DocumentRoleEvidence,
    FormulationAssemblyState,
    FormulationRowOwnerType,
    MaterialConstituent,
    SupplierMaterial,
)
from backend.app.models.formulation import (
    FormulationConcentration,
    FormulationIngredientRequest,
)
from backend.app.services.trade_name_assembly import (
    _identity_group,
    derive_assembly_state,
    formulation_row_ownership,
    matched_trade_material_row_ids,
    prepare_trade_name_assembly,
)
from backend.app.models.screening import (
    IdentityOutcome,
    IdentityStatus,
    IdentitySuggestion,
    IdentitySuggestionStatus,
    RegulatedFunction,
)
from backend.app.services.formulation import screen_formulation
from backend.app.services.formulation_assembly import prepare_assembly
from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.ingredient_linkage import load_accepted_ingredient_linkages
from backend.app.services.loader import load_accepted_store


def _quantity(kind: str, **values) -> CompositionQuantity:
    return CompositionQuantity.model_validate({"kind": kind, **values})


def test_supplier_material_owns_matching_trade_name_and_product_code_rows() -> None:
    session = AgentSessionView(
        session_id="version-1",
        revision=1,
        state=AgentSessionState.NEEDS_CONFIRMATION,
        filename="formula.csv",
        interpreted_rows=[
            AgentIngredientRow(
                row_id="trade-name-row",
                source_row=2,
                source_rows=[2],
                source_cells=["LumiMatrix 3000", "4%"],
                name=AgentFieldProvenance(
                    value="Unresolved material",
                    source_value="LumiMatrix 3000",
                    source_row=2,
                    interpretation_method="source_value",
                ),
                identity_status=AgentConfidence.NEEDS_CONFIRMATION,
            ),
            AgentIngredientRow(
                row_id="direct-row",
                source_row=3,
                source_rows=[3],
                source_cells=["GLYCERIN", "3%"],
                name=AgentFieldProvenance(
                    value="GLYCERIN",
                    source_value="GLYCERIN",
                    source_row=3,
                    interpretation_method="exact_name",
                ),
                identity_status=AgentConfidence.CONFIRMED,
            ),
        ],
    )
    material = SupplierMaterial(
        material_id="material-1",
        trade_name="LumiMatrix 3000",
        product_code="LMX-3000",
    )

    assert matched_trade_material_row_ids(session, [material]) == {"trade-name-row"}

    ownership = {item.row_id: item for item in formulation_row_ownership(session, [material])}
    assert ownership["trade-name-row"].owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
    assert ownership["trade-name-row"].material_id == "material-1"
    assert ownership["direct-row"].owner_type == FormulationRowOwnerType.DIRECT_INGREDIENT


def test_ambiguous_exact_material_match_stays_supplier_owned_without_selecting_one() -> None:
    session = AgentSessionView(
        session_id="version-1",
        revision=1,
        state=AgentSessionState.NEEDS_CONFIRMATION,
        filename="formula.csv",
        interpreted_rows=[AgentIngredientRow(
            row_id="shared-trade-row",
            source_row=2,
            source_rows=[2],
            source_cells=["Shared Blend", "2%"],
            name=AgentFieldProvenance(
                value="Shared Blend",
                source_value="Shared Blend",
                source_row=2,
                interpretation_method="source_value",
            ),
            identity_status=AgentConfidence.NEEDS_CONFIRMATION,
        )],
    )
    materials = [
        SupplierMaterial(material_id="material-a", trade_name="Shared Blend", supplier_name="A"),
        SupplierMaterial(material_id="material-b", trade_name="Shared Blend", supplier_name="B"),
    ]

    ownership = formulation_row_ownership(session, materials)

    assert len(ownership) == 1
    assert ownership[0].owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
    assert ownership[0].material_id is None
    assert ownership[0].candidate_material_ids == ["material-a", "material-b"]
    assert matched_trade_material_row_ids(session, materials) == {"shared-trade-row"}


def test_genuine_name_cas_conflict_is_not_treated_as_verified_for_aggregation(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly.resolve_ingredient",
        lambda *args, **kwargs: SimpleNamespace(
            status=IdentityStatus.REVIEW_REQUIRED,
            identity_outcome=IdentityOutcome.GENUINE_NAME_CAS_CONFLICT,
            catalogue_identity=SimpleNamespace(ingredient_id="wrong"),
            resolved_singapore_substance_ids=[],
            resolved_singapore_substance_id=None,
        ),
    )

    assert _identity_group(object(), None, None, "GLYCERIN", "122-99-6") is None


def test_name_recognised_with_unmapped_cas_can_retain_safe_name_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly.resolve_ingredient",
        lambda *args, **kwargs: SimpleNamespace(
            status=IdentityStatus.REVIEW_REQUIRED,
            identity_outcome=IdentityOutcome.NAME_RECOGNISED_CAS_UNVERIFIED,
            catalogue_identity=SimpleNamespace(ingredient_id="glycerin"),
            resolved_singapore_substance_ids=[],
            resolved_singapore_substance_id=None,
        ),
    )

    assert _identity_group(object(), None, None, "GLYCERIN", "111-11-1") == "catalogue:glycerin"


def test_ai_name_suggestion_stays_unidentified_until_reviewer_confirms() -> None:
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    linkages = load_accepted_ingredient_linkages()
    aqua = catalogue.find_exact_name("AQUA")
    assert aqua is not None
    suggestion = IdentitySuggestion(
        target_id="supplier-water",
        original_name="Water",
        canonical_name=aqua["canonical_name"],
        catalogue_ingredient_id=aqua["ingredient_id"],
        explanation="Water is the common-language name for the INCI name AQUA.",
        model="test-model",
    )
    state = FormulationAssemblyState(
        direct_ingredients=[DirectIngredient(
            ingredient_id="direct-aqua",
            ingredient=FormulationIngredientRequest(
                name="AQUA",
                concentration=FormulationConcentration(
                    concentration_type="exact",
                    value=5,
                    unit="percent",
                    basis=None,
                    preparation_stage="finished_product",
                ),
            ),
            source_document_id="primary:formula",
        )],
        materials=[SupplierMaterial(
            material_id="supplier-blend",
            trade_name="Supplier Blend",
            finished_product_usage=_quantity(
                "exact", value=10, unit="percent",
                quantity_scope="finished_product", preparation_stage="finished_product",
            ),
            attached_document_ids=["supplier.pdf"],
            governing_document_id="supplier.pdf",
            constituents=[MaterialConstituent(
                constituent_id="supplier-water",
                submitted_name="Water",
                composition_quantity=_quantity(
                    "exact", value=50, unit="percent", quantity_scope="supplier_material",
                ),
                identity_suggestion=suggestion,
            )],
            disclosure_status=DisclosureStatus.COMPLETE,
            confirmation_status=ConfirmationStatus.CONFIRMED,
        )],
        source_document_ids=["primary:formula", "supplier.pdf"],
    )

    pending_state, pending = prepare_trade_name_assembly(
        assembly_revision=1,
        state=state,
        formulation_id="formula",
        source_filename="formula.xlsx",
        store=store,
        catalogue=catalogue,
        linkages=linkages,
    )

    assert pending.formulation is not None
    assert [item.name for item in pending.formulation.ingredients] == ["AQUA", "Water"]
    screened = screen_formulation(
        store, pending.formulation, ingredient_catalog=catalogue, linkage_store=linkages,
    )
    water_result = next(
        item for item in screened.ingredient_results if item.submitted_ingredient.name == "Water"
    )
    assert water_result.primary_finding.value == "identity_unresolved"
    assert water_result.submitted_ingredient.identity_suggestion is not None
    assert water_result.submitted_ingredient.identity_suggestion.status == "pending"

    confirmed = pending_state.materials[0].constituents[0].model_copy(update={
        "identity_suggestion": suggestion.model_copy(update={
            "status": IdentitySuggestionStatus.CONFIRMED,
        }),
    })
    confirmed_state = pending_state.model_copy(update={
        "materials": [pending_state.materials[0].model_copy(update={
            "constituents": [confirmed],
        })],
    })
    _, accepted = prepare_trade_name_assembly(
        assembly_revision=2,
        state=confirmed_state,
        formulation_id="formula",
        source_filename="formula.xlsx",
        store=store,
        catalogue=catalogue,
        linkages=linkages,
    )

    assert accepted.formulation is not None
    assert len(accepted.formulation.ingredients) == 1
    assert accepted.formulation.ingredients[0].name == "AQUA"
    assert accepted.formulation.ingredients[0].concentration is not None
    assert accepted.formulation.ingredients[0].concentration.value == pytest.approx(10)


def test_test_a_combines_verified_source_alias_and_inci_before_screening() -> None:
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    linkages = load_accepted_ingredient_linkages()
    direct_identity = _identity_group(
        store, catalogue, linkages, "2-Phenoxyethanol", None,
    )
    supplier_identity = _identity_group(
        store, catalogue, linkages, "PHENOXYETHANOL", "122-99-6",
    )

    assert direct_identity == supplier_identity
    assert direct_identity is not None

    direct = DirectIngredient(
        ingredient_id="formula:phenoxyethanol",
        source_document_id="primary:test-a",
        verified_identity_group=direct_identity,
        ingredient=FormulationIngredientRequest(
            name="2-Phenoxyethanol",
            regulated_functions=[RegulatedFunction.PRESERVATIVE],
            concentration=FormulationConcentration(
                concentration_type="exact",
                value=1,
                unit="percent",
                basis=None,
                preparation_stage="finished_product",
            ),
        ),
    )
    supplier = SupplierMaterial(
        material_id="aegismix-p80",
        trade_name="AegisMix P80",
        supplier_name="Example Supplier",
        finished_product_usage=_quantity(
            "exact", value=0.75, unit="percent",
            quantity_scope="finished_product", preparation_stage="finished_product",
        ),
        attached_document_ids=["aegismix-p80.pdf"],
        governing_document_id="aegismix-p80.pdf",
        constituents=[MaterialConstituent(
            constituent_id="aegismix:phenoxyethanol",
            submitted_name="PHENOXYETHANOL",
            cas_number="122-99-6",
            composition_quantity=_quantity(
                "range", lower=36, upper=48, unit="percent",
                quantity_scope="supplier_material",
            ),
            verified_identity_group=supplier_identity,
        )],
        disclosure_status=DisclosureStatus.COMPLETE,
        confirmation_status=ConfirmationStatus.CONFIRMED,
    )

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[direct],
        materials=[supplier],
        source_filename="test-a.xlsx",
        source_document_ids=["primary:test-a", "aegismix-p80.pdf"],
    )

    assert prepared.formulation is not None
    assert len(prepared.formulation.ingredients) == 1
    combined = prepared.formulation.ingredients[0]
    assert combined.name == "2-Phenoxyethanol"
    assert combined.concentration is not None
    assert combined.concentration.lower_bound == pytest.approx(1.27)
    assert combined.concentration.upper_bound == pytest.approx(1.36)

    screened = screen_formulation(
        store,
        prepared.formulation,
        ingredient_catalog=catalogue,
        linkage_store=linkages,
    )
    assert len(screened.ingredient_results) == 1
    result = screened.ingredient_results[0]
    screened_concentration = result.submitted_ingredient.concentration
    assert screened_concentration is not None
    assert screened_concentration.lower_bound == pytest.approx(1.27)
    assert screened_concentration.upper_bound == pytest.approx(1.36)
    assert result.primary_finding.value == "permitted_use_condition_not_met"
    assert len(prepared.result.included_ingredients[0].contributions) == 2


def test_three_supplier_fixture_combines_all_phenoxyethanol_before_screening() -> None:
    store = load_accepted_store()
    catalogue = load_accepted_ingredient_catalog()
    linkages = load_accepted_ingredient_linkages()
    direct_identity = _identity_group(
        store, catalogue, linkages, "PHENOXYETHANOL", "122-99-6",
    )
    aegis_identity = _identity_group(
        store, catalogue, linkages, "PHENOXYETHANOL", "122-99-6",
    )
    bexa_identity = _identity_group(
        store, catalogue, linkages, "2-PHENOXYETHANOL", "122-99-6",
    )
    cava_identity = _identity_group(
        store, catalogue, linkages, "PHENOXYETHANOL", "122-99-6",
    )

    assert direct_identity is not None
    assert {direct_identity, aegis_identity, bexa_identity, cava_identity} == {direct_identity}

    direct = DirectIngredient(
        ingredient_id="formula:phenoxyethanol",
        source_document_id="primary:test-a",
        verified_identity_group=direct_identity,
        ingredient=FormulationIngredientRequest(
            name="PHENOXYETHANOL",
            cas_number="122-99-6",
            regulated_functions=[RegulatedFunction.PRESERVATIVE],
            concentration=FormulationConcentration(
                concentration_type="exact",
                value=0.1,
                unit="percent",
                basis=None,
                preparation_stage="finished_product",
            ),
        ),
    )

    def supplier(
        material_id: str,
        trade_name: str,
        usage: float,
        identity: str | None,
        *,
        value: float | None = None,
        lower: float | None = None,
        upper: float | None = None,
        submitted_name: str = "PHENOXYETHANOL",
    ) -> SupplierMaterial:
        quantity = (
            _quantity("exact", value=value, unit="percent", quantity_scope="supplier_material")
            if value is not None
            else _quantity("range", lower=lower, upper=upper, unit="percent", quantity_scope="supplier_material")
        )
        return SupplierMaterial(
            material_id=material_id,
            trade_name=trade_name,
            finished_product_usage=_quantity(
                "exact", value=usage, unit="percent",
                quantity_scope="finished_product", preparation_stage="finished_product",
            ),
            attached_document_ids=[f"{material_id}.pdf"],
            governing_document_id=f"{material_id}.pdf",
            constituents=[MaterialConstituent(
                constituent_id=f"{material_id}:phenoxyethanol",
                submitted_name=submitted_name,
                cas_number="122-99-6",
                composition_quantity=quantity,
                verified_identity_group=identity,
            )],
            disclosure_status=DisclosureStatus.COMPLETE,
            confirmation_status=ConfirmationStatus.CONFIRMED,
        )

    prepared = prepare_assembly(
        assembly_revision=1,
        direct_ingredients=[direct],
        materials=[
            supplier("aegis", "AegisMix P80", 0.75, aegis_identity, value=80),
            supplier(
                "bexa", "BexaBlend R45", 0.9, bexa_identity,
                lower=30, upper=40, submitted_name="2-PHENOXYETHANOL",
            ),
            supplier("cava", "CavaBase P25", 1.2, cava_identity, value=25),
        ],
        source_filename="A_00_Finished_Formula_MULTI_SHEET.xlsx",
    )

    assert prepared.formulation is not None
    assert len(prepared.formulation.ingredients) == 1
    combined = prepared.formulation.ingredients[0]
    assert combined.concentration is not None
    assert combined.concentration.lower_bound == pytest.approx(1.27)
    assert combined.concentration.upper_bound == pytest.approx(1.36)
    assert len(prepared.result.included_ingredients) == 1
    assert len(prepared.result.included_ingredients[0].contributions) == 4

    screened = screen_formulation(
        store,
        prepared.formulation,
        ingredient_catalog=catalogue,
        linkage_store=linkages,
    )
    assert len(screened.ingredient_results) == 1
    result = screened.ingredient_results[0]
    assert result.submitted_ingredient.concentration is not None
    assert result.submitted_ingredient.concentration.lower_bound == pytest.approx(1.27)
    assert result.submitted_ingredient.concentration.upper_bound == pytest.approx(1.36)
    assert result.primary_finding.value == "permitted_use_condition_not_met"


def _extraction() -> DocumentExtraction:
    document_id = "doc-1"
    return DocumentExtraction(
        document_id=document_id,
        classification=DocumentClassification(
            proposed_roles=[DocumentRoleEvidence(
                role=DocumentRole.SUPPLIER_COMPOSITION,
                confidence="high",
            )],
            trade_name="OPTASENSE",
            recommended_extraction_schema="supplier_composition",
        ),
        supplier_materials=[SupplierMaterial(
            material_id="doc-1:material:1",
            trade_name="OPTASENSE",
            attached_document_ids=[document_id],
            constituents=[MaterialConstituent(
                constituent_id="doc-1:constituent:1",
                submitted_name="GLYCERIN",
                cas_number="56-81-5",
                composition_quantity=_quantity(
                    "coded_range",
                    reported_code="C",
                    raw_text="C",
                    quantity_scope="supplier_material",
                ),
            )],
        )],
        legends=[CompositionLegend(
            legend_id="doc-1:legend:1",
            document_id=document_id,
            entries=[CompositionLegendEntry(
                entry_id="doc-1:legend:1:C",
                code="C",
                raw_definition="C = 25-50%",
                normalized_quantity=_quantity(
                    "range",
                    lower=25,
                    upper=50,
                    unit="percent",
                    quantity_scope="supplier_material",
                ),
            )],
        )],
        extraction_schema_version="trade-document-v1",
    )


def _revision_extraction(document_id: str, concentration: float) -> DocumentExtraction:
    return DocumentExtraction(
        document_id=document_id,
        classification=DocumentClassification(
            proposed_roles=[DocumentRoleEvidence(
                role=DocumentRole.SUPPLIER_COMPOSITION,
                confidence="high",
            )],
            trade_name="OPTASENSE",
            product_code="EN80159",
            recommended_extraction_schema="supplier_composition",
        ),
        supplier_materials=[SupplierMaterial(
            material_id=f"{document_id}:material:1",
            trade_name="OPTASENSE",
            product_code="EN80159",
            constituents=[MaterialConstituent(
                constituent_id=f"{document_id}:constituent:1",
                submitted_name="GLYCERIN",
                cas_number="56-81-5",
                composition_quantity=_quantity(
                    "exact", value=concentration, unit="percent",
                    quantity_scope="supplier_material",
                ),
            )],
        )],
        extraction_schema_version="trade-document-v1",
    )


def test_derive_state_resolves_document_local_legend_and_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )
    state = derive_assembly_state(
        version_id="version-1",
        formulation_name="Pilot serum",
        agent_state=None,
        documents=[{
            "id": "doc-1",
            "confirmed_roles": ["supplier_composition"],
            "governing_for_material": True,
            "extraction_result": _extraction().model_dump(mode="json"),
        }],
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )

    material = state.materials[0]
    assert material.confirmation_status == ConfirmationStatus.CONFIRMED
    assert material.governing_document_id == "doc-1"
    quantity = material.constituents[0].composition_quantity
    assert quantity is not None
    assert quantity.kind.value == "range"
    assert quantity.lower == 25
    assert quantity.upper == 50
    assert quantity.legend_entry_id == "doc-1:legend:1:C"
    assert material.constituents[0].verified_identity_group == "catalogue:glycerin"


def test_derive_state_resolves_library_legend_after_formulation_attachment(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )
    extraction = _extraction()
    state = derive_assembly_state(
        version_id="version-1",
        formulation_name="Pilot serum",
        agent_state=None,
        documents=[{
            "id": "formulation-attachment-1",
            "supplier_document_id": "doc-1",
            "confirmed_roles": ["supplier_composition"],
            "governing_for_material": True,
            "extraction_result": extraction.model_dump(mode="json"),
        }],
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )

    material = state.materials[0]
    quantity = material.constituents[0].composition_quantity
    assert material.governing_document_id == "formulation-attachment-1"
    assert quantity is not None
    assert quantity.kind.value == "range"
    assert quantity.lower == 25
    assert quantity.upper == 50
    assert quantity.legend_entry_id == "doc-1:legend:1:C"


def test_legacy_high_confidence_supplier_document_calculates_without_role_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )

    state = derive_assembly_state(
        version_id="version-1",
        formulation_name="Pilot serum",
        agent_state=None,
        documents=[{
            "id": "doc-1",
            "confirmed_roles": [],
            "governing_for_material": False,
            "extraction_result": _extraction().model_dump(mode="json"),
        }],
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )

    assert len(state.materials) == 1
    assert state.materials[0].governing_document_id == "doc-1"
    assert state.materials[0].confirmation_status == ConfirmationStatus.CONFIRMED


def test_sds_disclosure_is_partial_and_persists_in_screening_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )
    extraction = _extraction()
    state = derive_assembly_state(
        version_id="version-1",
        formulation_name="Pilot serum",
        agent_state=None,
        documents=[{
            "id": "doc-1",
            "confirmed_roles": ["sds_msds"],
            "governing_for_material": True,
            "extraction_result": extraction.model_dump(mode="json"),
        }],
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )
    material = state.materials[0].model_copy(update={
        "finished_product_usage": _quantity(
            "exact",
            value=2,
            unit="percent",
            preparation_stage="finished_product",
            quantity_scope="finished_product",
            raw_text="2%",
        ),
    })
    state = state.model_copy(update={"materials": [material]})
    normalized, prepared = prepare_trade_name_assembly(
        assembly_revision=2,
        state=state,
        formulation_id="version-1",
        source_filename="pilot.csv",
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )

    assert normalized.materials[0].disclosure_status == DisclosureStatus.PARTIAL
    assert prepared.formulation is not None
    assert prepared.formulation.document_completeness.value == "partial_disclosure"
    assert prepared.formulation.assembly_scope is not None
    assert prepared.formulation.assembly_scope.completeness == "partial"
    assert "incomplete_supplier_disclosure" in prepared.formulation.assembly_scope.issue_codes
    assert prepared.formulation.assembly_scope.action_required_codes == []
    assert "incomplete_supplier_disclosure" in (
        prepared.formulation.assembly_scope.coverage_limitation_codes
    )
    assert prepared.formulation.assembly_scope.source_document_ids == ["doc-1", "primary:version-1"]


def test_missing_material_usage_is_preserved_as_unknown_not_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )
    material = SupplierMaterial(
        material_id="material-1",
        trade_name="OPTASENSE",
        attached_document_ids=["doc-1"],
        governing_document_id="doc-1",
        confirmation_status=ConfirmationStatus.CONFIRMED,
        disclosure_status=DisclosureStatus.COMPLETE,
        constituents=[MaterialConstituent(
            constituent_id="glycerin",
            submitted_name="GLYCERIN",
            cas_number="56-81-5",
            verified_identity_group="catalogue:glycerin",
            composition_quantity=_quantity(
                "exact",
                value=100,
                unit="percent",
                quantity_scope="supplier_material",
                raw_text="100%",
            ),
        )],
    )
    _, prepared = prepare_trade_name_assembly(
        assembly_revision=1,
        state=FormulationAssemblyState(
            materials=[material],
            source_document_ids=["doc-1"],
        ),
        formulation_id="version-1",
        source_filename="pilot.csv",
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )

    assert prepared.formulation is not None
    concentration = prepared.formulation.ingredients[0].concentration
    assert concentration is not None
    assert concentration.concentration_type.value == "unknown"
    assert prepared.formulation.assembly_scope is not None
    assert "material_usage_missing" in prepared.formulation.assembly_scope.issue_codes


def test_reviewer_cannot_persist_a_malformed_constituent_cas() -> None:
    with pytest.raises(ValidationError, match="valid syntax and checksum"):
        MaterialConstituent(
            constituent_id="bad-cas",
            submitted_name="Example ingredient",
            cas_number="123-45-6",
        )


def test_conflicting_supplier_revisions_are_grouped_without_double_counting(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )
    documents = [{
        "id": document_id,
        "confirmed_roles": ["supplier_composition"],
        "governing_for_material": True,
        "extraction_result": _revision_extraction(document_id, concentration).model_dump(mode="json"),
    } for document_id, concentration in (("doc-old", 25), ("doc-new", 40))]

    state = derive_assembly_state(
        version_id="version-1", formulation_name="Pilot", agent_state=None,
        documents=documents, store=object(), catalogue=None, linkages=None,  # type: ignore[arg-type]
    )

    assert len(state.materials) == 1
    material = state.materials[0]
    assert material.governing_document_id is None
    assert material.conflicting_document_ids == ["doc-new", "doc-old"]
    _, prepared = prepare_trade_name_assembly(
        assembly_revision=1, state=state, formulation_id="version-1",
        source_filename="pilot.csv", store=object(), catalogue=None, linkages=None,  # type: ignore[arg-type]
    )
    assert "composition_statement_conflict" in {
        issue.code for issue in prepared.result.issues
    }
    assert prepared.result.evaluated_scope["material_count"] == 1


def test_one_governing_revision_selects_only_that_supplier_composition(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )
    documents = [{
        "id": document_id,
        "confirmed_roles": ["supplier_composition"],
        "governing_for_material": document_id == "doc-new",
        "extraction_result": _revision_extraction(document_id, concentration).model_dump(mode="json"),
    } for document_id, concentration in (("doc-old", 25), ("doc-new", 40))]

    state = derive_assembly_state(
        version_id="version-1", formulation_name="Pilot", agent_state=None,
        documents=documents, store=object(), catalogue=None, linkages=None,  # type: ignore[arg-type]
    )

    material = state.materials[0]
    assert material.governing_document_id == "doc-new"
    assert material.conflicting_document_ids == []
    assert material.constituents[0].composition_quantity.value == 40


def test_finished_formulation_trade_name_usage_populates_parent_material(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:glycerin",
    )
    agent_state = {
        "session_id": "version-1",
        "revision": 1,
        "state": "interpreted",
        "filename": "formula.csv",
        "interpreted_rows": [{
            "row_id": "trade-row",
            "source_row": 2,
            "source_cells": ["OPTASENSE", "2%"],
            "name": {
                "value": "OPTASENSE", "source_value": "OPTASENSE",
                "source_row": 2, "interpretation_method": "exact_source",
            },
            "concentration": {
                "concentration_type": {
                    "value": "exact", "source_value": "2%", "source_row": 2,
                    "interpretation_method": "exact_source",
                },
                "value": {
                    "value": 2, "source_value": "2%", "source_row": 2,
                    "interpretation_method": "parsed_source",
                },
                "original_text": "2%",
                "unit": {
                    "value": "percent", "source_value": "%", "source_row": 2,
                    "interpretation_method": "exact_source",
                },
                "basis": {
                    "value": None, "source_value": None, "source_row": 2,
                    "interpretation_method": "not_supplied",
                },
                "preparation_stage": {
                    "value": "finished_product", "source_value": "finished product",
                    "source_row": 2, "interpretation_method": "exact_source",
                },
            },
            "identity_status": "unresolved",
        }],
    }
    extraction = _extraction()
    state = derive_assembly_state(
        version_id="version-1", formulation_name="Pilot", agent_state=agent_state,
        documents=[{
            "id": "doc-1", "confirmed_roles": ["supplier_composition"],
            "governing_for_material": True,
            "extraction_result": extraction.model_dump(mode="json"),
        }],
        store=object(), catalogue=None, linkages=None,  # type: ignore[arg-type]
    )

    material = state.materials[0]
    assert material.finished_product_usage is not None
    assert material.finished_product_usage.value == 2
    assert material.finished_product_usage.quantity_scope == "finished_product"
    assert all(row.ingredient.name != "OPTASENSE" for row in state.direct_ingredients)
    assert state.formulation_row_ownership[0].row_id == "trade-row"
    assert state.formulation_row_ownership[0].owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
    assert state.formulation_row_ownership[0].material_id == material.material_id


def test_direct_qs_row_remains_in_assembly_provenance(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda *args, **kwargs: "catalogue:aqua",
    )
    agent_state = {
        "session_id": "version-1",
        "revision": 1,
        "state": "interpreted",
        "filename": "formula.csv",
        "interpreted_rows": [{
            "row_id": "aqua-row",
            "source_row": 2,
            "source_cells": ["AQUA", "7732-18-5", "q.s. to 100%"],
            "name": {
                "value": "AQUA", "source_value": "AQUA",
                "source_row": 2, "interpretation_method": "exact_source",
            },
            "cas_number": {
                "value": "7732-18-5", "source_value": "7732-18-5",
                "source_row": 2, "interpretation_method": "source_value_preserved",
            },
            "concentration": None,
            "identity_status": "confirmed",
            "unresolved_fields": [{
                "target_field": "concentration",
                "uncertainty_code": "concentration_unavailable",
                "source_value": "q.s. to 100%",
            }],
        }],
    }

    state = derive_assembly_state(
        version_id="version-1",
        formulation_name="Pilot",
        agent_state=agent_state,
        documents=[],
        store=object(),
        catalogue=None,
        linkages=None,  # type: ignore[arg-type]
    )

    assert len(state.direct_ingredients) == 1
    concentration = state.direct_ingredients[0].ingredient.concentration
    assert concentration is not None
    assert concentration.concentration_type.value == "unknown"
    assert concentration.original_text == "q.s. to 100%"
    assert concentration.unit.value == "percent"


def test_filename_material_alias_owns_parent_row_and_legacy_direct_rows_are_ignored(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "backend.app.services.trade_name_assembly._identity_group",
        lambda _store, _catalogue, _linkages, name, _cas: (
            f"catalogue:{name.casefold().replace(' ', '-')}"
        ),
    )
    agent_state = {
        "session_id": "version-1",
        "revision": 1,
        "state": "interpreted",
        "filename": "formula.xlsx",
        "interpreted_rows": [
            {
                "row_id": "material-row",
                "source_row": 2,
                "source_cells": ["ClariPreserve P70", "1%"],
                "name": {
                    "value": "ClariPreserve P70",
                    "source_value": "ClariPreserve P70",
                    "source_row": 2,
                    "interpretation_method": "exact_source",
                },
                "concentration": {
                    "concentration_type": {
                        "value": "exact", "source_value": "1%", "source_row": 2,
                        "interpretation_method": "exact_source",
                    },
                    "value": {
                        "value": 1, "source_value": "1%", "source_row": 2,
                        "interpretation_method": "parsed_source",
                    },
                    "original_text": "1%",
                    "unit": {
                        "value": "percent", "source_value": "%", "source_row": 2,
                        "interpretation_method": "exact_source",
                    },
                    "basis": {
                        "value": None, "source_value": None, "source_row": 2,
                        "interpretation_method": "not_supplied",
                    },
                    "preparation_stage": {
                        "value": "finished_product", "source_value": "finished product",
                        "source_row": 2, "interpretation_method": "exact_source",
                    },
                },
                "identity_status": "unresolved",
            },
            {
                "row_id": "aqua-row",
                "source_row": 3,
                "source_cells": ["AQUA", "91%"],
                "name": {
                    "value": "AQUA", "source_value": "AQUA", "source_row": 3,
                    "interpretation_method": "exact_name",
                },
                "concentration": {
                    "concentration_type": {
                        "value": "exact", "source_value": "91%", "source_row": 3,
                        "interpretation_method": "exact_source",
                    },
                    "value": {
                        "value": 91, "source_value": "91%", "source_row": 3,
                        "interpretation_method": "parsed_source",
                    },
                    "original_text": "91%",
                    "unit": {
                        "value": "percent", "source_value": "%", "source_row": 3,
                        "interpretation_method": "exact_source",
                    },
                    "basis": {
                        "value": None, "source_value": None, "source_row": 3,
                        "interpretation_method": "not_supplied",
                    },
                    "preparation_stage": {
                        "value": "finished_product", "source_value": "finished product",
                        "source_row": 3, "interpretation_method": "exact_source",
                    },
                },
                "identity_status": "confirmed",
            },
        ],
    }
    extraction = DocumentExtraction(
        document_id="supplier-doc",
        classification=DocumentClassification(
            proposed_roles=[DocumentRoleEvidence(
                role=DocumentRole.SUPPLIER_COMPOSITION,
                confidence="high",
            )],
            recommended_extraction_schema="supplier_composition",
        ),
        supplier_materials=[SupplierMaterial(
            material_id="supplier-doc:material:1",
            trade_name="01_ClariPreserve_P70_Supplier_Composition.pdf",
            constituents=[MaterialConstituent(
                constituent_id="phenoxyethanol",
                submitted_name="PHENOXYETHANOL",
                composition_quantity=_quantity(
                    "exact", value=70, unit="percent",
                    quantity_scope="supplier_material",
                ),
            )],
        )],
        # Some older extraction snapshots retained a direct representation as
        # well as the supplier-material representation. It must not be counted.
        direct_ingredients=[DirectIngredient(
            ingredient_id="legacy-direct-phenoxyethanol",
            ingredient=FormulationIngredientRequest(
                name="PHENOXYETHANOL",
                    concentration=FormulationConcentration(
                        value=70,
                        unit="percent",
                        basis=None,
                        preparation_stage="finished_product",
                    ),
            ),
            source_document_id="supplier-doc",
        )],
        extraction_schema_version="trade-document-v1",
    )

    state = derive_assembly_state(
        version_id="version-1",
        formulation_name="Pilot",
        agent_state=agent_state,
        documents=[{
            "id": "supplier-doc",
            "confirmed_roles": ["supplier_composition"],
            "governing_for_material": True,
            "extraction_result": extraction.model_dump(mode="json"),
        }],
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )

    assert state.materials[0].finished_product_usage is not None
    assert state.materials[0].finished_product_usage.value == 1
    assert [row.ingredient.name for row in state.direct_ingredients] == ["AQUA"]
    ownership = {item.row_id: item for item in state.formulation_row_ownership}
    assert ownership["material-row"].owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
    assert ownership["material-row"].material_id == state.materials[0].material_id
    assert ownership["aqua-row"].owner_type == FormulationRowOwnerType.DIRECT_INGREDIENT

    _, prepared = prepare_trade_name_assembly(
        assembly_revision=1,
        state=state,
        formulation_id="version-1",
        source_filename="formula.xlsx",
        store=object(),  # type: ignore[arg-type]
        catalogue=None,
        linkages=None,
    )
    aggregates = {
        item.display_name: item.aggregate_quantity
        for item in prepared.result.included_ingredients
    }
    assert aggregates["PHENOXYETHANOL"].value == pytest.approx(0.7)
    assert aggregates["AQUA"].value == 91
    assert "impossible_composition_total" not in {
        issue.code for issue in prepared.result.issues
    }

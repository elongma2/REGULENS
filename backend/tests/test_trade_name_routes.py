from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.requests import Request
from fastapi import HTTPException

from backend.app.dependencies import CurrentUser
from backend.app.models.agent import AgentSessionState, AgentSessionView
from backend.app.models.agent import AgentPrepareRequest, AgentPreparedFormulation
from backend.app.models.document_intake import (
    CompositionQuantity,
    DirectIngredient,
    FormulationAssemblyState,
    MaterialConstituent,
    SupplierMaterial,
)
from backend.app.models.formulation import FormulationIngredientRequest
from backend.app.models.formulation import FormulationAssemblyScope, FormulationRequest
from backend.app.routes.cases import (
    _current_formulation_documents,
    _merge_assembly_state,
    _record_supporting_document_failures,
    delete_supplier_document,
    get_formulation_assembly,
    interpret_formulation_document,
    prepare_formulation,
    screen_persistent_formulation,
)
from backend.app.services.supplier_documents import SupplierDocumentProcessingError
from backend.app.services.supabase_gateway import SupplierDocumentDeletionError


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_assembly_refresh_reprocesses_stale_supplier_and_replaces_attachment_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment_id = UUID("33333333-3333-3333-8333-333333333333")
    supplier_id = UUID("44444444-4444-4444-8444-444444444444")
    attachment = {
        "id": str(attachment_id),
        "supplier_document_id": str(supplier_id),
        "revision": 2,
        "processing_status": "ready",
        "attached_extraction_key": "old-schema-key",
        "extraction_result": {"supplier_materials": [{"trade_name": "Old"}]},
    }
    supplier = {
        "id": str(supplier_id),
        "processing_key": "old-schema-key",
        "sha256": "a" * 64,
    }
    refreshed = {
        **attachment,
        "revision": 3,
        "attached_extraction_key": "current-schema-key",
        "extraction_result": {"supplier_materials": [{"trade_name": "RangeShield P30"}]},
    }
    calls: list[tuple[str, object]] = []
    gateway = SimpleNamespace(
        list_formulation_documents=lambda *_: [attachment],
        get_supplier_document_detail=lambda *_: supplier,
        refresh_formulation_document_from_supplier=lambda user_id, document_id, expected_revision: (
            calls.append(("refresh", (document_id, expected_revision))) or refreshed
        ),
    )
    service = SimpleNamespace(
        extraction_is_compatible=lambda *args, **kwargs: False,
        retry_processing=lambda **kwargs: (
            calls.append(("retry", kwargs["document_id"]))
            or {**supplier, "processing_key": "current-schema-key"}
        ),
    )
    monkeypatch.setattr(
        "backend.app.routes.cases.SupplierDocumentService",
        lambda _gateway: service,
    )
    request = Request({
        "type": "http",
        "method": "POST",
        "path": f"/formulations/{VERSION_ID}/assembly/refresh",
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(
            document_vision_extractor=None,
            document_text_extractor=None,
        )),
    })

    documents = _current_formulation_documents(
        request=request,
        gateway=gateway,
        user=CurrentUser(id=USER_ID, email="reviewer@example.com"),
        version_id=VERSION_ID,
    )

    assert documents == [refreshed]
    assert calls == [
        ("retry", supplier_id),
        ("refresh", (attachment_id, 2)),
    ]


def test_get_assembly_restores_state_without_incrementing_revision_or_persisting() -> None:
    state = FormulationAssemblyState(
        formulation_name="Saved trade-material review",
        source_document_ids=["document-1"],
    )

    def unexpected_persist(*args, **kwargs):
        raise AssertionError("reading a saved assembly must not write it again")

    gateway = SimpleNamespace(
        get_version=lambda user_id, version_id: {
            "id": str(version_id),
            "original_filename": "pilot.csv",
            "assembly_revision": 7,
            "assembly_state": state.model_dump(mode="json"),
        },
        persist_assembly=unexpected_persist,
    )
    request = Request({
        "type": "http",
        "method": "GET",
        "path": f"/formulations/{VERSION_ID}/assembly",
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(
            regulatory_store=object(),
            ingredient_catalog=None,
            ingredient_linkage=None,
        )),
    })

    response = get_formulation_assembly(
        VERSION_ID,
        request,
        CurrentUser(id=USER_ID, email="reviewer@example.com"),
        gateway,
    )

    assert response.assembly_revision == 7
    assert response.state.formulation_name == "Saved trade-material review"
    assert response.state.source_document_ids == ["document-1"]
    assert response.assembly.assembly_revision == 7


def test_supporting_document_failure_preserves_version_and_records_retry_message() -> None:
    persisted: list[dict] = []

    def persist_agent_state(
        user_id, version_id, expected_revision, status, agent_state,
        canonical_formulation, product_context, clarifications,
    ):
        persisted.append({
            "expected_revision": expected_revision,
            "status": status,
            "agent_state": agent_state,
        })

    gateway = SimpleNamespace(
        get_version=lambda user_id, version_id: {"revision": 4},
        persist_agent_state=persist_agent_state,
    )
    view = AgentSessionView(
        session_id=str(VERSION_ID),
        revision=4,
        state=AgentSessionState.NEEDS_CONFIRMATION,
        filename="pilot.csv",
        source_format="csv",
        model="test-model",
    )

    _record_supporting_document_failures(
        gateway,
        CurrentUser(id=USER_ID, email="reviewer@example.com"),
        VERSION_ID,
        view,
        ["supplier.pdf", "supplier.pdf", "composition.pdf"],
    )

    assert persisted[0]["expected_revision"] == 4
    assert persisted[0]["agent_state"]["revision"] == 5
    assert persisted[0]["agent_state"]["activity"][-1]["status"] == "warning"
    assert persisted[0]["agent_state"]["activity"][-1]["message"].endswith(
        "supplier.pdf, composition.pdf"
    )


def test_refresh_merges_new_source_snapshot_without_losing_reviewer_edits() -> None:
    edited = MaterialConstituent(
        constituent_id="row-1",
        submitted_name="GLYCERIN USP",
        cas_number="56-81-5",
        composition_quantity=CompositionQuantity(
            kind="exact", value=40, unit="percent", quantity_scope="supplier_material"
        ),
        user_edits={"submitted_name": "GLYCERIN USP"},
    )
    existing = FormulationAssemblyState(
        materials=[SupplierMaterial(
            material_id="material-1",
            trade_name="Saved blend",
            constituents=[edited, MaterialConstituent(
                constituent_id="reviewer:new",
                submitted_name="PANTHENOL",
                user_edits={"added_by_reviewer": True},
            )],
            removed_constituent_ids=["row-2"],
            finished_product_usage=CompositionQuantity(
                kind="exact", value=2, unit="percent",
                quantity_scope="finished_product", preparation_stage="finished_product",
            ),
        )],
        source_document_ids=["doc-1"],
        source_document_snapshots={"doc-1": "old"},
    )
    discovered = FormulationAssemblyState(
        materials=[SupplierMaterial(
            material_id="material-1",
            trade_name="Saved blend",
            constituents=[MaterialConstituent(
                constituent_id="row-1",
                submitted_name="GLYCERIN",
                cas_number="56-81-5",
                composition_quantity=CompositionQuantity(
                    kind="exact", value=45, unit="percent",
                    quantity_scope="supplier_material",
                ),
            ), MaterialConstituent(
                constituent_id="row-2",
                submitted_name="AQUA",
                cas_number="7732-18-5",
            )],
        )],
        source_document_ids=["doc-1"],
        source_document_snapshots={"doc-1": "new"},
    )

    merged = _merge_assembly_state(existing, discovered)

    assert merged.source_document_snapshots == {"doc-1": "new"}
    assert merged.materials[0].finished_product_usage.value == 2
    assert [item.submitted_name for item in merged.materials[0].constituents] == [
        "GLYCERIN USP", "PANTHENOL",
    ]
    assert merged.materials[0].removed_constituent_ids == ["row-2"]


def test_refresh_does_not_apply_stale_row_edits_to_a_different_reextracted_identity() -> None:
    existing = FormulationAssemblyState(materials=[SupplierMaterial(
        material_id="material-1",
        trade_name="RangeShield P30",
        constituents=[MaterialConstituent(
            constituent_id="row-1",
            submitted_name="TEST FIXTURE ONLY",
            user_edits={"submitted_name": "Reviewed footer"},
        )],
    )])
    discovered = FormulationAssemblyState(materials=[SupplierMaterial(
        material_id="material-1",
        trade_name="RangeShield P30",
        disclosure_status="complete",
        constituents=[MaterialConstituent(
            constituent_id="row-1",
            submitted_name="PHENOXYETHANOL",
            cas_number="122-99-6",
            composition_quantity=CompositionQuantity(
                kind="range",
                lower=20,
                upper=40,
                unit="percent",
                quantity_scope="supplier_material",
            ),
        )],
    )])

    merged = _merge_assembly_state(existing, discovered)

    constituent = merged.materials[0].constituents[0]
    assert constituent.submitted_name == "PHENOXYETHANOL"
    assert constituent.cas_number == "122-99-6"
    assert constituent.user_edits == {}
    assert merged.materials[0].disclosure_status.value == "complete"


def test_refresh_drops_direct_rows_from_detached_documents() -> None:
    existing = FormulationAssemblyState(
        direct_ingredients=[DirectIngredient(
            ingredient_id="document:old:row-1",
            ingredient=FormulationIngredientRequest(name="OLD SOURCE INGREDIENT"),
            source_document_id="old-document",
        )],
        source_document_ids=["old-document"],
    )
    discovered = FormulationAssemblyState(
        direct_ingredients=[DirectIngredient(
            ingredient_id="agent:row-1",
            ingredient=FormulationIngredientRequest(name="CURRENT INGREDIENT"),
            source_document_id="primary:version-1",
        )],
        source_document_ids=["primary:version-1"],
    )

    merged = _merge_assembly_state(existing, discovered)

    assert [row.ingredient.name for row in merged.direct_ingredients] == [
        "CURRENT INGREDIENT",
    ]


def test_refresh_uses_newly_discovered_formula_usage_when_saved_snapshot_was_empty() -> None:
    existing = FormulationAssemblyState(materials=[SupplierMaterial(
        material_id="material-1",
        trade_name="ClariPreserve P70",
        finished_product_usage=None,
    )])
    discovered = FormulationAssemblyState(materials=[SupplierMaterial(
        material_id="material-1",
        trade_name="ClariPreserve P70",
        finished_product_usage=CompositionQuantity(
            kind="exact",
            value=1,
            unit="percent",
            quantity_scope="finished_product",
            preparation_stage="finished_product",
        ),
    )])

    merged = _merge_assembly_state(existing, discovered)

    assert merged.materials[0].finished_product_usage is not None
    assert merged.materials[0].finished_product_usage.value == 1


def test_supplier_document_delete_requires_an_unreferenced_private_source() -> None:
    deleted: list[tuple[UUID, UUID]] = []
    document_id = UUID("33333333-3333-3333-3333-333333333333")
    gateway = SimpleNamespace(
        delete_supplier_document=lambda user_id, target_id: deleted.append((user_id, target_id)),
    )

    delete_supplier_document(
        document_id,
        CurrentUser(id=USER_ID, email="reviewer@example.com"),
        gateway,
    )

    assert deleted == [(USER_ID, document_id)]


def test_supplier_document_delete_returns_conflict_while_referenced() -> None:
    document_id = UUID("33333333-3333-3333-3333-333333333333")

    def blocked(*args, **kwargs):
        raise SupplierDocumentDeletionError("still attached")

    with pytest.raises(HTTPException) as caught:
        delete_supplier_document(
            document_id,
            CurrentUser(id=USER_ID, email="reviewer@example.com"),
            SimpleNamespace(delete_supplier_document=blocked),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "supplier_document_deletion_blocked"


def test_interpret_failure_refreshes_formulation_snapshot_for_safe_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = UUID("33333333-3333-3333-3333-333333333333")
    supplier_id = UUID("44444444-4444-4444-4444-444444444444")
    refreshed: list[tuple[UUID, int]] = []

    def fail_processing(*args, **kwargs):
        raise SupplierDocumentProcessingError(
            "document_vision_not_configured",
            "Vision is not configured",
        )

    monkeypatch.setattr(
        "backend.app.routes.cases.SupplierDocumentService.retry_processing",
        fail_processing,
    )
    gateway = SimpleNamespace(
        get_formulation_document=lambda user_id, target_id: {
            "id": str(target_id),
            "supplier_document_id": str(supplier_id),
            "processing_status": "uploaded",
            "revision": 2,
        },
        get_supplier_document_detail=lambda user_id, target_id: {
            "id": str(target_id),
            "extraction_schema_version": None,
            "extraction_result": None,
        },
        refresh_formulation_document_from_supplier=lambda user_id, target_id, *, expected_revision: (
            refreshed.append((target_id, expected_revision)) or {}
        ),
    )
    request = Request({
        "type": "http",
        "method": "POST",
        "path": f"/formulation-documents/{document_id}/interpret",
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(document_vision_extractor=None)),
    })

    with pytest.raises(HTTPException) as caught:
        interpret_formulation_document(
            document_id,
            request,
            CurrentUser(id=USER_ID, email="reviewer@example.com"),
            gateway,
        )

    assert caught.value.status_code == 503
    assert refreshed == [(document_id, 2)]


def test_agent_prepare_rebuilds_trade_material_canonical_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AgentSessionView(
        session_id=str(VERSION_ID),
        revision=3,
        state=AgentSessionState.READY,
        filename="pilot.csv",
        source_format="csv",
        model="test-model",
    )
    flat = FormulationRequest(
        ingredients=[FormulationIngredientRequest(name="AQUA")],
    )
    calculated = FormulationRequest(
        assembly_scope=FormulationAssemblyScope(
            completeness="partial",
            issue_codes=["incomplete_supplier_disclosure"],
            source_document_ids=["document-1"],
        ),
        ingredients=[FormulationIngredientRequest(name="GLYCERIN")],
    )
    prepared = AgentPreparedFormulation(
        session=session,
        formulation=flat,
        row_provenance=[],
    )
    monkeypatch.setattr(
        "backend.app.routes.cases._hydrate",
        lambda *args: ({"revision": 3}, session),
    )
    prepare_kwargs = {}
    def prepare_agent(session_id, payload, **kwargs):
        prepare_kwargs.update(kwargs)
        return prepared.model_copy(update={
            "session": prepared.session.model_copy(update={
                "canonical_formulation": kwargs.get("formulation_override"),
            }),
            "formulation": kwargs.get("formulation_override"),
        })
    monkeypatch.setattr(
        "backend.app.routes.cases._agent_service",
        lambda request: SimpleNamespace(prepare=prepare_agent),
    )
    monkeypatch.setattr("backend.app.routes.cases._persist", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "backend.app.routes.cases.refresh_formulation_assembly",
        lambda *args, **kwargs: SimpleNamespace(
            assembly_revision=8,
            formulation=calculated.model_dump(mode="json"),
            state=FormulationAssemblyState(),
        ),
    )
    gateway = SimpleNamespace(
        list_formulation_documents=lambda user_id, version_id: [{"extraction_result": {"supplier_materials": [{}]}}],
    )
    request = Request({
        "type": "http", "method": "POST", "path": "/prepare", "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace()),
    })

    result = prepare_formulation(
        VERSION_ID,
        AgentPrepareRequest(revision=3),
        request,
        CurrentUser(id=USER_ID, email="reviewer@example.com"),
        gateway,
    )

    assert result.formulation.ingredients[0].name == "GLYCERIN"
    assert result.formulation.assembly_scope is not None
    assert result.formulation.assembly_scope.completeness == "partial"
    assert result.formulation.input_revision is not None
    assert result.formulation.input_revision.agent_revision == 3
    assert result.formulation.input_revision.assembly_revision == 8
    assert prepare_kwargs["formulation_override"].ingredients[0].name == "GLYCERIN"


def test_screening_waits_for_every_retained_supporting_document() -> None:
    gateway = SimpleNamespace(
        get_version=lambda user_id, version_id: {
            "canonical_formulation": FormulationRequest(
                ingredients=[FormulationIngredientRequest(name="AQUA")],
            ).model_dump(mode="json"),
        },
        list_formulation_documents=lambda user_id, version_id: [{
            "original_filename": "supplier-scan.pdf",
            "processing_status": "interrupted",
        }],
    )
    request = Request({
        "type": "http", "method": "POST", "path": "/screen", "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace()),
    })

    with pytest.raises(HTTPException) as caught:
        screen_persistent_formulation(
            VERSION_ID,
            request,
            CurrentUser(id=USER_ID, email="reviewer@example.com"),
            gateway,
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "supporting_documents_not_ready"


def test_screening_uses_single_action_copy_when_assembly_is_stale() -> None:
    gateway = SimpleNamespace(
        get_version=lambda user_id, version_id: {
            "canonical_formulation": FormulationRequest(
                ingredients=[FormulationIngredientRequest(name="AQUA")],
            ).model_dump(mode="json"),
        },
        list_formulation_documents=lambda user_id, version_id: [{
            "processing_status": "ready",
            "extraction_result": {"supplier_materials": [{}]},
        }],
    )
    request = Request({
        "type": "http", "method": "POST", "path": "/screen", "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace()),
    })

    with pytest.raises(HTTPException) as caught:
        screen_persistent_formulation(
            VERSION_ID,
            request,
            CurrentUser(id=USER_ID, email="reviewer@example.com"),
            gateway,
        )

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "formulation_assembly_not_prepared",
        "message": "Source information changed. Review the highlighted input and run screening again.",
    }


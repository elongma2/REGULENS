from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.app.models.document_intake import (
    DocumentClassification,
    DocumentExtraction,
    DocumentRole,
    DocumentRoleEvidence,
    SupplierMaterial,
)
from backend.app.services.agent_csv import CSVUploadError, ParsedCSV
from backend.app.services.document_vision import VisionExtraction
from backend.app.services.document_text import TextDocumentExtraction
from backend.app.services.supplier_documents import (
    SupplierDocumentProcessingError,
    SupplierDocumentService,
    _automatic_supplier_role,
)
from backend.app.services.supabase_gateway import SupabaseGateway


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")
CASE_ID = UUID("33333333-3333-3333-3333-333333333333")
ORG_ID = UUID("44444444-4444-4444-4444-444444444444")


def test_structured_supplier_hierarchy_wins_over_a_generic_document_recommendation() -> None:
    extraction = DocumentExtraction(
        document_id="document-1",
        classification=DocumentClassification(
            proposed_roles=[
                DocumentRoleEvidence(
                    role=DocumentRole.FINISHED_PRODUCT_FORMULATION,
                    confidence="medium",
                ),
                DocumentRoleEvidence(
                    role=DocumentRole.SUPPLIER_COMPOSITION,
                    confidence="high",
                ),
            ],
            recommended_extraction_schema="finished_product_formulation",
        ),
        supplier_materials=[SupplierMaterial(
            material_id="material-1",
            trade_name="LumiMatrix 3000",
            constituents=[],
        )],
        extraction_schema_version="trade-document-v1",
    )

    assert _automatic_supplier_role(extraction) == DocumentRole.SUPPLIER_COMPOSITION


class _SnapshotQuery:
    def __init__(self, client: "_SnapshotClient", table: str):
        self.client = client
        self.table = table
        self.operation = "select"
        self.payload: dict[str, object] = {}
        self.filters: dict[str, str] = {}

    def select(self, _columns: str) -> "_SnapshotQuery":
        self.operation = "select"
        return self

    def insert(self, row: dict[str, object]) -> "_SnapshotQuery":
        self.operation = "insert"
        self.payload = deepcopy(row)
        return self

    def update(self, changes: dict[str, object]) -> "_SnapshotQuery":
        self.operation = "update"
        self.payload = deepcopy(changes)
        return self

    def eq(self, field: str, value: object) -> "_SnapshotQuery":
        self.filters[field] = str(value)
        return self

    def limit(self, _count: int) -> "_SnapshotQuery":
        return self

    def execute(self) -> SimpleNamespace:
        rows = [
            row for row in self.client.rows.setdefault(self.table, [])
            if all(str(row.get(field)) == value for field, value in self.filters.items())
        ]
        if self.operation == "insert":
            inserted = {
                "id": str(uuid4()),
                "revision": 0,
                **deepcopy(self.payload),
            }
            self.client.rows[self.table].append(inserted)
            rows = [inserted]
        elif self.operation == "update":
            for row in rows:
                row.update(deepcopy(self.payload))
        return SimpleNamespace(data=deepcopy(rows))


class _SnapshotClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {
            "formulation_documents": [],
            "supplier_documents": [],
        }

    def table(self, name: str) -> _SnapshotQuery:
        return _SnapshotQuery(self, name)


def _gateway() -> SimpleNamespace:
    now = datetime.now(UTC).isoformat()
    state: dict[str, object] = {
        "existing": None,
        "uploaded": [],
        "removed": [],
        "created": [],
        "persisted": [],
        "attached": [],
        "detail": None,
        "source": None,
    }

    def upload_file(path: str, content: bytes, content_type: str | None) -> None:
        state["uploaded"].append((path, content, content_type))  # type: ignore[union-attr]

    def remove_file(path: str) -> None:
        state["removed"].append(path)  # type: ignore[union-attr]

    def create_supplier_document(*args, **kwargs):
        state["created"].append(kwargs)  # type: ignore[union-attr]
        return ({
            "id": str(kwargs["document_id"]),
            "revision": 0,
            "created_at": now,
            "updated_at": now,
        }, False)

    def persist_supplier_document_processing(user_id, document_id, *, expected_revision, changes):
        state["persisted"].append((document_id, expected_revision, changes))  # type: ignore[union-attr]
        source = state.get("source")
        source_row = source[0] if isinstance(source, tuple) else {}
        return {
            **source_row,
            "id": str(document_id),
            "revision": expected_revision + 1,
            **changes,
        }

    def attach_supplier_document(user_id, version_id, document_id):
        state["attached"].append((version_id, document_id))  # type: ignore[union-attr]
        return {"id": "attachment", "supplier_document_id": str(document_id)}

    gateway = SimpleNamespace(
        state=state,
        get_version=lambda user_id, version_id: {"id": str(version_id), "case_id": str(CASE_ID)},
        get_case=lambda user_id, case_id: {"id": str(case_id), "organisation_id": str(ORG_ID)},
        find_supplier_document_by_hash=lambda *args: state["existing"],
        upload_file=upload_file,
        remove_file=remove_file,
        create_supplier_document=create_supplier_document,
        persist_supplier_document_processing=persist_supplier_document_processing,
        attach_supplier_document=attach_supplier_document,
        get_supplier_document_detail=lambda *args: state["detail"],
        update_supplier_document=lambda user_id, document_id, *, expected_revision, changes: {
            "id": str(document_id), "revision": expected_revision + 1, **changes
        },
        download_supplier_document_source=lambda *args: state["source"],
    )
    return gateway


def test_existing_hash_attaches_without_upload_or_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = _gateway()
    existing_id = uuid4()
    later_version_id = uuid4()
    gateway.state["existing"] = {"id": str(existing_id)}
    monkeypatch.setattr(
        "backend.app.services.supplier_documents.parse_formulation_upload",
        lambda *args: pytest.fail("a saved exact document must not be parsed again"),
    )

    service = SupplierDocumentService(gateway)
    attachment, reused = service.upload_and_attach(
        user_id=USER_ID,
        version_id=VERSION_ID,
        filename="supplier.pdf",
        content=b"same private file",
        content_type="application/pdf",
    )
    later_attachment, later_reused = service.upload_and_attach(
        user_id=USER_ID,
        version_id=later_version_id,
        filename="renamed-copy.pdf",
        content=b"same private file",
        content_type="application/pdf",
    )

    assert reused is True
    assert later_reused is True
    assert attachment["supplier_document_id"] == str(existing_id)
    assert later_attachment["supplier_document_id"] == str(existing_id)
    assert gateway.state["attached"] == [
        (VERSION_ID, existing_id),
        (later_version_id, existing_id),
    ]
    assert gateway.state["uploaded"] == []
    assert gateway.state["persisted"] == []


def test_saved_extraction_compatibility_checks_schema_and_processor_configuration() -> None:
    deterministic = {
        "extraction_schema_version": "trade-document-v2",
        "extraction_result": {"supplier_materials": [{}]},
        "model_configuration": "deterministic-trade-document-v1",
        "processing_diagnostics": {"model_calls": 0},
    }
    assert SupplierDocumentService.extraction_is_compatible(
        deterministic,
        vision_extractor=None,
    ) is True
    assert SupplierDocumentService.extraction_is_compatible(
        {**deterministic, "extraction_schema_version": "older-schema"},
        vision_extractor=None,
    ) is False

    vision = {
        **deterministic,
        "model_configuration": "bounded-openai-document-vision-v1",
        "processing_diagnostics": {
            "model_calls": 1,
            "configured_model": "low-cost-document-model",
        },
    }
    assert SupplierDocumentService.extraction_is_compatible(
        vision,
        vision_extractor=SimpleNamespace(model="low-cost-document-model"),
    ) is True
    assert SupplierDocumentService.extraction_is_compatible(
        vision,
        vision_extractor=SimpleNamespace(model="new-document-model"),
    ) is False


def test_saved_document_attachment_snapshots_exact_extraction_until_explicit_refresh() -> None:
    client = _SnapshotClient()
    supplier_id = uuid4()
    source = {
        "id": str(supplier_id),
        "organisation_id": str(ORG_ID),
        "original_filename": "supplier-sds.pdf",
        "mime_type": "application/pdf",
        "sha256": "a" * 64,
        "page_count": 2,
        "processing_status": "ready",
        "detected_roles": [{"role": "sds_msds"}],
        "confirmed_roles": ["sds_msds"],
        "parsed_content": {"rows": [["old source row"]]},
        "extraction_result": {"supplier_materials": [{"trade_name": "Blend revision 1"}]},
        "processing_diagnostics": {"model_calls": 0},
        "processing_key": "hash:schema-v1:processor-v1",
        "document_revision_label": "Revision 1",
    }
    client.rows["supplier_documents"].append(source)
    gateway = object.__new__(SupabaseGateway)
    gateway.client = client
    gateway._version_row = lambda _user_id, _version_id: {  # type: ignore[method-assign]
        "id": str(VERSION_ID), "case_id": str(CASE_ID),
    }
    gateway._case_row = lambda _user_id, _case_id: {  # type: ignore[method-assign]
        "id": str(CASE_ID), "organisation_id": str(ORG_ID),
    }
    gateway._supplier_document_row = lambda _user_id, _document_id: source  # type: ignore[method-assign]
    gateway._formulation_document_row = lambda _user_id, document_id: next(  # type: ignore[method-assign]
        row for row in client.rows["formulation_documents"] if row["id"] == str(document_id)
    )

    attached = gateway.attach_supplier_document(USER_ID, VERSION_ID, supplier_id)
    attachment_id = UUID(str(attached["id"]))
    source["parsed_content"] = {"rows": [["new source row"]]}
    source["extraction_result"] = {"supplier_materials": [{"trade_name": "Blend revision 2"}]}
    source["processing_key"] = "hash:schema-v2:processor-v2"
    source["document_revision_label"] = "Revision 2"

    unchanged = gateway.get_formulation_document(USER_ID, attachment_id)
    assert unchanged["parsed_content"] == {"rows": [["old source row"]]}
    assert unchanged["extraction_result"]["supplier_materials"][0]["trade_name"] == "Blend revision 1"
    assert unchanged["attached_extraction_key"] == "hash:schema-v1:processor-v1"
    assert unchanged["document_revision_label"] == "Revision 1"

    refreshed = gateway.refresh_formulation_document_from_supplier(
        USER_ID,
        attachment_id,
        expected_revision=0,
    )
    assert refreshed["parsed_content"] == {"rows": [["new source row"]]}
    assert refreshed["extraction_result"]["supplier_materials"][0]["trade_name"] == "Blend revision 2"
    assert refreshed["attached_extraction_key"] == "hash:schema-v2:processor-v2"
    assert refreshed["document_revision_label"] == "Revision 2"
    assert refreshed["revision"] == 1


def test_selectable_text_falls_back_to_one_structured_low_cost_interpretation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()
    document_id = uuid4()
    source_rows = (("Unfamiliar supplier layout",), ("Component A appears at five percent",))
    gateway.state["source"] = ({
        "id": str(document_id), "organisation_id": str(ORG_ID), "revision": 1,
        "original_filename": "unfamiliar.pdf", "sha256": "c" * 64,
        "confirmed_roles": [], "processing_attempt": 0,
    }, b"selectable-text-pdf")
    monkeypatch.setattr(
        "backend.app.services.supplier_documents.parse_formulation_upload",
        lambda *_args: ParsedCSV(
            filename="unfamiliar.pdf", delimiter=",", rows=source_rows,
            source_format="pdf", row_pages=(1, 1), row_snippets=(source_rows[0][0], source_rows[1][0]),
            page_count=1,
        ),
    )
    interpreted = ParsedCSV(
        filename="unfamiliar.pdf", delimiter=",",
        rows=(("Product Name: Example Blend",), ("Ingredient name", "CAS No.", "Concentration"), ("GLYCERIN", "56-81-5", "5%")),
        source_format="pdf", row_pages=(1, None, 1), row_snippets=("Example Blend", None, "GLYCERIN 56-81-5 5%"), page_count=1,
    )
    calls: list[str] = []
    text_extractor = SimpleNamespace(
        model="low-cost-document-model",
        extract_text=lambda filename, parsed: (
            calls.append(filename) or TextDocumentExtraction(
                parsed=interpreted,
                diagnostics={
                    "processor": "bounded-openai-document-text-v1",
                    "configured_model": "low-cost-document-model",
                    "model_calls": 1,
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "total_tokens": 30,
                },
            )
        ),
    )

    result = SupplierDocumentService(gateway).retry_processing(
        user_id=USER_ID,
        document_id=document_id,
        vision_extractor=None,
        text_extractor=text_extractor,
    )

    assert calls == ["unfamiliar.pdf"]
    assert result["processing_status"] == "ready"
    assert result["confirmed_roles"] == ["supplier_composition"]
    assert result["library_status"] == "available"
    assert result["model_configuration"] == "bounded-openai-document-text-v1"
    assert result["processing_diagnostics"]["model_calls"] == 1
    assert result["parsed_content"]["rows"] == [list(row) for row in source_rows]
    assert result["extraction_result"]["supplier_materials"][0]["constituents"][0]["submitted_name"] == "GLYCERIN"


def test_unrecognised_selectable_text_is_recoverable_when_interpreter_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()
    document_id = uuid4()
    gateway.state["source"] = ({
        "id": str(document_id), "organisation_id": str(ORG_ID), "revision": 1,
        "original_filename": "unfamiliar.pdf", "sha256": "d" * 64,
        "confirmed_roles": [], "processing_attempt": 0,
    }, b"selectable-text-pdf")
    monkeypatch.setattr(
        "backend.app.services.supplier_documents.parse_formulation_upload",
        lambda *_args: ParsedCSV(
            filename="unfamiliar.pdf", delimiter=",",
            rows=(("Unfamiliar supplier layout",),), source_format="pdf",
            row_pages=(1,), row_snippets=("Unfamiliar supplier layout",), page_count=1,
        ),
    )

    with pytest.raises(SupplierDocumentProcessingError) as captured:
        SupplierDocumentService(gateway).retry_processing(
            user_id=USER_ID,
            document_id=document_id,
            vision_extractor=None,
            text_extractor=None,
        )

    assert captured.value.code == "document_text_interpretation_not_configured"
    assert captured.value.recoverable is True
    assert gateway.state["persisted"][-1][2]["processing_status"] == "interrupted"


def test_supplier_revision_lineage_rejects_self_cycles_and_cross_organisation_links() -> None:
    first_id = UUID("55555555-5555-4555-8555-555555555551")
    second_id = UUID("55555555-5555-4555-8555-555555555552")
    other_id = UUID("55555555-5555-4555-8555-555555555553")
    rows = {
        first_id: {
            "id": str(first_id), "organisation_id": str(ORG_ID), "revision": 0,
            "supersedes_supplier_document_id": str(second_id),
        },
        second_id: {
            "id": str(second_id), "organisation_id": str(ORG_ID), "revision": 0,
            "supersedes_supplier_document_id": None,
        },
        other_id: {
            "id": str(other_id), "organisation_id": str(uuid4()), "revision": 0,
            "supersedes_supplier_document_id": None,
        },
    }
    gateway = object.__new__(SupabaseGateway)
    gateway._supplier_document_row = lambda _user_id, document_id: rows[document_id]  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="cannot supersede itself"):
        gateway.update_supplier_document(
            USER_ID, second_id, expected_revision=0,
            changes={"supersedes_supplier_document_id": str(second_id)},
        )
    with pytest.raises(ValueError, match="cannot contain a cycle"):
        gateway.update_supplier_document(
            USER_ID, second_id, expected_revision=0,
            changes={"supersedes_supplier_document_id": str(first_id)},
        )
    with pytest.raises(ValueError, match="same organisation"):
        gateway.update_supplier_document(
            USER_ID, second_id, expected_revision=0,
            changes={"supersedes_supplier_document_id": str(other_id)},
        )


def test_new_supplier_composition_is_stored_extracted_and_attached() -> None:
    gateway = _gateway()
    content = (
        "Supplier: Example Materials\n"
        "Product Name: OPTASENSE RMA\n"
        "INCI Name,CAS No.,Concentration\n"
        "GLYCERIN,56-81-5,25-50%\n"
    ).encode()

    _, reused = SupplierDocumentService(gateway).upload_and_attach(
        user_id=USER_ID,
        version_id=VERSION_ID,
        filename="optasense.csv",
        content=content,
        content_type="text/csv",
    )

    assert reused is False
    assert len(gateway.state["uploaded"]) == 1
    changes = gateway.state["persisted"][0][2]
    assert changes["trade_name"] == "OPTASENSE RMA"
    assert changes["model_configuration"] == "deterministic-trade-document-v1"
    assert changes["processing_diagnostics"]["model_calls"] == 0
    assert changes["extraction_result"]["supplier_materials"][0]["constituents"][0][
        "composition_quantity"
    ]["quantity_scope"] == "supplier_material"
    assert len(gateway.state["attached"]) == 1


def test_deferred_upload_persists_private_source_without_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()
    monkeypatch.setattr(
        "backend.app.services.supplier_documents.parse_formulation_upload",
        lambda *args: pytest.fail("deferred upload must not parse in the upload request"),
    )

    attachment, reused = SupplierDocumentService(gateway).upload_and_attach(
        user_id=USER_ID,
        version_id=VERSION_ID,
        filename="supplier-composition.pdf",
        content=b"private-pdf",
        content_type="application/pdf",
        process_immediately=False,
    )

    assert reused is False
    assert attachment["supplier_document_id"]
    assert len(gateway.state["uploaded"]) == 1
    assert gateway.state["created"][0]["processing_status"] == "uploaded"
    assert gateway.state["created"][0]["library_status"] == "processing"
    assert gateway.state["persisted"] == []


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("empty.pdf", b"", "agent_csv_empty"),
        ("unsupported.docx", b"not-empty", "agent_csv_type_unsupported"),
    ],
)
def test_deferred_upload_rejects_invalid_input_before_private_storage(
    filename: str,
    content: bytes,
    code: str,
) -> None:
    gateway = _gateway()

    with pytest.raises(CSVUploadError) as captured:
        SupplierDocumentService(gateway).upload_and_attach(
            user_id=USER_ID,
            version_id=VERSION_ID,
            filename=filename,
            content=content,
            content_type="application/octet-stream",
            process_immediately=False,
        )

    assert captured.value.code == code
    assert gateway.state["uploaded"] == []


def test_image_only_pdf_is_retained_for_retry_without_reupload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()
    monkeypatch.setattr(
        "backend.app.services.supplier_documents.parse_formulation_upload",
        lambda *args: (_ for _ in ()).throw(CSVUploadError(
            "agent_pdf_text_unavailable",
            "Unable to extract text",
        )),
    )
    monkeypatch.setattr(
        "backend.app.services.supplier_documents._pdf_page_count",
        lambda content: 6,
    )

    SupplierDocumentService(gateway).upload_and_attach(
        user_id=USER_ID,
        version_id=VERSION_ID,
        filename="sicare.pdf",
        content=b"image-only-placeholder",
        content_type="application/pdf",
    )

    created = gateway.state["created"][0]
    assert created["page_count"] == 6
    changes = gateway.state["persisted"][0][2]
    assert changes["processing_status"] == "interrupted"
    assert changes["error"]["recoverable"] is True
    assert changes["error"]["next_action"] == "ocr_or_vision_retry"
    assert len(gateway.state["uploaded"]) == 1
    assert len(gateway.state["attached"]) == 1


def test_only_confirmed_supplier_roles_can_become_available() -> None:
    gateway = _gateway()
    document_id = uuid4()
    gateway.state["detail"] = {
        "id": str(document_id),
        "confirmed_roles": [],
        "extraction_result": {"supplier_materials": []},
    }
    service = SupplierDocumentService(gateway)

    with pytest.raises(ValueError, match="confirmed SDS/MSDS or supplier-composition"):
        service.confirm_library_metadata(
            user_id=USER_ID,
            document_id=document_id,
            expected_revision=0,
            changes={"confirmed_roles": ["ingredient_list"], "library_status": "available"},
        )

    result = service.confirm_library_metadata(
        user_id=USER_ID,
        document_id=document_id,
        expected_revision=0,
        changes={"confirmed_roles": ["supplier_composition"], "library_status": "available"},
    )
    assert result["library_status"] == "available"


def test_retry_uses_retained_private_pdf_and_bounded_vision_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()
    document_id = uuid4()
    gateway.state["source"] = ({
        "id": str(document_id),
        "organisation_id": str(ORG_ID),
        "revision": 2,
        "original_filename": "sicare.pdf",
        "sha256": "b" * 64,
        "confirmed_roles": ["sds_msds"],
        "supplier_name": None,
        "trade_name": None,
        "product_code": None,
        "document_revision_label": None,
        "processing_attempt": 1,
    }, b"retained-private-pdf")
    monkeypatch.setattr(
        "backend.app.services.supplier_documents.parse_formulation_upload",
        lambda *args: (_ for _ in ()).throw(CSVUploadError(
            "agent_pdf_text_unavailable",
            "No selectable text",
        )),
    )

    class FakeVision:
        calls = 0

        def extract_pdf(self, filename: str, content: bytes) -> VisionExtraction:
            self.calls += 1
            assert filename == "sicare.pdf"
            assert content == b"retained-private-pdf"
            parsed = ParsedCSV(
                filename=filename,
                delimiter=",",
                rows=(
                    ("Product Name: SiCare 2315F3",),
                    ("Ingredient name", "CAS No.", "Concentration"),
                    ("DIMETHICONE", "9006-65-9", "50-75%"),
                ),
                source_format="pdf",
                row_pages=(1, None, 2),
                row_snippets=("Product Name: SiCare 2315F3", None, "DIMETHICONE 50-75%"),
                page_count=3,
            )
            return VisionExtraction(parsed=parsed, diagnostics={
                "processor": "fake-bounded-vision",
                "configured_model": "low-cost-test-model",
                "model_calls": 1,
            })

    vision = FakeVision()
    result = SupplierDocumentService(gateway).retry_processing(
        user_id=USER_ID,
        document_id=document_id,
        vision_extractor=vision,
    )

    assert vision.calls == 1
    assert gateway.state["uploaded"] == []
    changes = gateway.state["persisted"][-1][2]
    assert changes["processing_attempt"] == 2
    assert changes["processing_status"] == "ready"
    assert changes["confirmed_roles"] == ["sds_msds"]
    assert changes["library_status"] == "available"
    assert changes["processing_diagnostics"]["model_calls"] == 1
    assert changes["model_configuration"] == "fake-bounded-vision"
    assert changes["extraction_result"]["supplier_materials"][0]["trade_name"] == "SiCare 2315F3"
    assert result["error"] is None


def test_retry_preserves_image_only_source_when_vision_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()
    document_id = uuid4()
    gateway.state["source"] = ({
        "id": str(document_id),
        "organisation_id": str(ORG_ID),
        "revision": 1,
        "original_filename": "scan.pdf",
        "sha256": "c" * 64,
        "confirmed_roles": [],
        "processing_attempt": 1,
    }, b"retained-private-pdf")
    monkeypatch.setattr(
        "backend.app.services.supplier_documents.parse_formulation_upload",
        lambda *args: (_ for _ in ()).throw(CSVUploadError(
            "agent_pdf_text_unavailable",
            "No selectable text",
        )),
    )

    with pytest.raises(SupplierDocumentProcessingError) as captured:
        SupplierDocumentService(gateway).retry_processing(
            user_id=USER_ID,
            document_id=document_id,
            vision_extractor=None,
        )

    assert captured.value.code == "document_vision_not_configured"
    assert len(gateway.state["persisted"]) == 2
    failure = gateway.state["persisted"][-1][2]
    assert failure["processing_status"] == "interrupted"
    assert failure["error"]["code"] == "document_vision_not_configured"
    assert gateway.state["removed"] == []


def test_retry_does_not_duplicate_an_active_processing_lease() -> None:
    gateway = _gateway()
    document_id = uuid4()
    gateway.state["source"] = ({
        "id": str(document_id),
        "organisation_id": str(ORG_ID),
        "revision": 3,
        "original_filename": "composition.csv",
        "sha256": "d" * 64,
        "confirmed_roles": ["supplier_composition"],
        "processing_status": "extracting",
        "processing_attempt": 1,
        "lease_expires_at": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
    }, b"Ingredient,Concentration\nGLYCERIN,50%")

    with pytest.raises(SupplierDocumentProcessingError) as captured:
        SupplierDocumentService(gateway).retry_processing(
            user_id=USER_ID,
            document_id=document_id,
            vision_extractor=None,
        )

    assert captured.value.code == "document_processing_in_progress"
    assert gateway.state["persisted"] == []


def test_retry_takes_over_an_expired_processing_lease() -> None:
    gateway = _gateway()
    document_id = uuid4()
    gateway.state["source"] = ({
        "id": str(document_id),
        "organisation_id": str(ORG_ID),
        "revision": 3,
        "original_filename": "composition.csv",
        "sha256": "e" * 64,
        "confirmed_roles": ["supplier_composition"],
        "processing_status": "extracting",
        "processing_attempt": 1,
        "lease_expires_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        "supplier_name": None,
        "trade_name": None,
        "product_code": None,
        "document_revision_label": None,
    }, (
        b"Product Name: SAVED BLEND\n"
        b"Ingredient,CAS No.,Concentration\n"
        b"GLYCERIN,56-81-5,50%\n"
    ))

    result = SupplierDocumentService(gateway).retry_processing(
        user_id=USER_ID,
        document_id=document_id,
        vision_extractor=None,
    )

    assert result["processing_attempt"] == 2
    assert result["lease_expires_at"] is None
    assert len(gateway.state["persisted"]) == 2

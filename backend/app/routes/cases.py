from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from backend.app.dependencies import CurrentUser, get_current_user, get_supabase_gateway
from backend.app.models.agent import (
    AgentActivityItem,
    AgentAnswersRequest,
    AgentPrepareRequest,
    AgentPreparedFormulation,
    AgentSessionState,
    AgentSessionView,
    AgentFailure,
)
from backend.app.models.cases import (
    CaseCreate,
    CaseListItem,
    CaseUpdate,
    CaseView,
    CurrentUserView,
    FormulationVersionPatch,
    FormulationVersionSummary,
    FormulationVersionView,
    FormulationDocumentUpdate,
    FormulationDocumentView,
    FormulationDocumentBatchView,
    FormulationDocumentUploadFailure,
    AttachSupplierDocumentRequest,
    AssemblyPreparationView,
    AssemblyStateUpdate,
    PermanentDeleteRequest,
    ScreeningRunView,
    SignedFileView,
    SupplierDocumentDetailView,
    SupplierDocumentBatchView,
    SupplierDocumentUpdate,
    SupplierDocumentView,
)
from backend.app.models.formulation import (
    FormulationRequest,
    FormulationScreeningResponse,
    ScreeningInputRevision,
)
from backend.app.models.document_intake import FormulationAssemblyState, FormulationRowOwnerType
from backend.app.services.agent_csv import CSVUploadError, MAX_FILE_BYTES, ParsedCSV, parse_formulation_upload
from backend.app.services.formulation import screen_formulation
from backend.app.services.formulation_agent import (
    AgentConfirmationRequiredError,
    AgentRevisionConflictError,
    FormulationAgentService,
)
from backend.app.services.parsing import UnsupportedProductContextError
from backend.app.services.screening_report import build_screening_report, screening_report_filename
from backend.app.services.supplier_documents import (
    SupplierDocumentProcessingError,
    SupplierDocumentService,
)
from backend.app.services.document_batch import DocumentBatchError, select_primary_formulation
from backend.app.services.trade_name_assembly import (
    derive_assembly_state,
    prepare_trade_name_assembly,
)
from backend.app.services.supabase_gateway import (
    AccountDeletionBlockedError,
    AccountDeletionError,
    CaseDeletionError,
    FormulationDeletionError,
    ResourceNotFoundError,
    RevisionConflictError,
    SupplierDocumentDeletionError,
    SupabaseGateway,
)


router = APIRouter(tags=["cases"])
persistent_agent_router = APIRouter(prefix="/agent/formulations", tags=["formulation-agent"])
LOGGER = logging.getLogger(__name__)


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "resource_not_found", "message": str(error.args[0] if error.args else error)})


def _agent_service(request: Request) -> FormulationAgentService:
    service = getattr(request.app.state, "formulation_agent", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "agent_unavailable", "message": "The formulation agent is unavailable."})
    return service


def _parsed(raw: dict[str, Any]) -> ParsedCSV:
    return ParsedCSV(
        filename=str(raw["filename"]),
        delimiter=str(raw.get("delimiter") or ","),
        rows=tuple(tuple(str(cell) for cell in row) for row in raw["rows"]),
        source_format=str(raw.get("source_format") or "structured_grid"),
        row_pages=tuple(raw.get("row_pages") or ()),
        row_snippets=tuple(str(value) for value in (raw.get("row_snippets") or ())),
        page_count=raw.get("page_count"),
    )


def _raw(parsed: ParsedCSV) -> dict[str, Any]:
    return {
        "filename": parsed.filename,
        "delimiter": parsed.delimiter,
        "rows": [list(row) for row in parsed.rows],
        "source_format": parsed.source_format,
        "row_pages": list(parsed.row_pages),
        "row_snippets": list(parsed.row_snippets),
        "page_count": parsed.page_count,
    }


def _status(view: AgentSessionView) -> str:
    return {
        AgentSessionState.UPLOADED: "uploaded",
        AgentSessionState.PARSING: "interpreting",
        AgentSessionState.INTERPRETED: "interpreted",
        AgentSessionState.NEEDS_CONFIRMATION: "clarification_required",
        AgentSessionState.READY: "ready_to_screen",
        AgentSessionState.FAILED: "failed",
    }[view.state]


def _question_value(view: AgentSessionView, question: Any) -> tuple[Any, Any]:
    row = next((item for item in view.interpreted_rows if item.row_id == question.row_id), None)
    if row is None:
        return None, None
    field = question.target_field
    if field == "ingredient_name":
        return row.name.source_value, row.name.value
    if field == "cas_number" and row.cas_number:
        return row.cas_number.source_value, row.cas_number.value
    if field in {"concentration", "concentration.unit"} and row.concentration:
        source = (
            row.concentration.value.source_value
            if row.concentration.value and row.concentration.value.source_value
            else row.concentration.original_text
        )
        proposed = row.concentration.unit.value if field == "concentration.unit" and row.concentration.unit else {
            "concentration_type": (
                row.concentration.concentration_type.value
                if row.concentration.concentration_type else None
            ),
            "value": row.concentration.value.value if row.concentration.value else None,
            "lower_bound": row.concentration.lower_bound.value if row.concentration.lower_bound else None,
            "upper_bound": row.concentration.upper_bound.value if row.concentration.upper_bound else None,
            "lower_inclusive": row.concentration.lower_inclusive,
            "upper_inclusive": row.concentration.upper_inclusive,
        }
        return source, proposed
    if field == "preparation_stage" and row.concentration and row.concentration.preparation_stage:
        return row.concentration.preparation_stage.source_value, row.concentration.preparation_stage.value
    return None, None


def _clarifications(view: AgentSessionView) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for question in view.questions:
        if question.question_type == "ingredient_function":
            continue
        source, proposed = _question_value(view, question)
        items.append({
            "question_key": question.question_id,
            "row_id": question.row_id,
            "field_name": question.target_field or question.question_type,
            "uncertainty_code": question.uncertainty_code,
            "question": question.prompt,
            "source_value": source,
            "proposed_value": proposed,
        })
    return items


def _view_from_row(row: dict[str, Any]) -> FormulationVersionView:
    payload = {key: value for key, value in row.items() if key in FormulationVersionView.model_fields}
    agent_session = payload.get("agent_session")
    if isinstance(agent_session, dict):
        agent_session = dict(agent_session)
        agent_session["questions"] = [
            question
            for question in agent_session.get("questions", [])
            if question.get("question_type") not in {"document_completeness", "ingredient_function"}
        ]
        for row in agent_session.get("interpreted_rows", []):
            row["unresolved_fields"] = [
                uncertainty for uncertainty in row.get("unresolved_fields", [])
                if uncertainty.get("uncertainty_code") != "ingredient_function"
            ]
        agent_session["document_completeness_confirmed"] = True
        payload["agent_session"] = agent_session
    return FormulationVersionView.model_validate(payload)


def _summary(row: dict[str, Any]) -> FormulationVersionSummary:
    return FormulationVersionSummary.model_validate({
        key: value for key, value in row.items() if key in FormulationVersionSummary.model_fields
    })


def _case(model: type[CaseView] | type[CaseListItem], row: dict[str, Any]) -> CaseView | CaseListItem:
    return model.model_validate({key: value for key, value in row.items() if key in model.model_fields})


def _screening(
    row: dict[str, Any],
    version: dict[str, Any] | None = None,
) -> ScreeningRunView:
    payload = {
        key: value for key, value in row.items() if key in ScreeningRunView.model_fields
    }
    input_revision = (row.get("request_snapshot") or {}).get("input_revision")
    if version is not None and isinstance(input_revision, dict):
        payload["current_input_matches"] = (
            input_revision.get("agent_revision") == int(version.get("revision") or 0)
            and input_revision.get("assembly_revision")
            == int(version.get("assembly_revision") or 0)
        )
    return ScreeningRunView.model_validate(payload)


def _supplier_document(
    model: type[SupplierDocumentView] | type[SupplierDocumentDetailView],
    row: dict[str, Any],
) -> SupplierDocumentView | SupplierDocumentDetailView:
    return model.model_validate({key: value for key, value in row.items() if key in model.model_fields})


def _formulation_document(row: dict[str, Any]) -> FormulationDocumentView:
    return FormulationDocumentView.model_validate({
        key: value for key, value in row.items() if key in FormulationDocumentView.model_fields
    })


def _persist(
    gateway: SupabaseGateway,
    user: CurrentUser,
    version_id: UUID,
    expected_revision: int,
    view: AgentSessionView,
) -> None:
    try:
        gateway.persist_agent_state(
            user.id,
            version_id,
            expected_revision,
            _status(view),
            view.model_dump(mode="json"),
            view.canonical_formulation.model_dump(mode="json") if view.canonical_formulation else None,
            view.product_context.model_dump(mode="json") if view.product_context else None,
            _clarifications(view),
        )
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "agent_revision_conflict", "message": str(error)}) from error


def _record_supporting_document_failures(
    gateway: SupabaseGateway,
    user: CurrentUser,
    version_id: UUID,
    view: AgentSessionView,
    filenames: list[str],
) -> None:
    if not filenames:
        return
    current = gateway.get_version(user.id, version_id)
    view.revision = int(current["revision"]) + 1
    view.activity.append(AgentActivityItem(
        activity_id=str(uuid4()),
        status="warning",
        message=(
            "Formulation preserved. Upload these supporting documents again: "
            + ", ".join(dict.fromkeys(filenames))
        ),
    ))
    _persist(gateway, user, version_id, int(current["revision"]), view)


def _hydrate(
    request: Request,
    gateway: SupabaseGateway,
    user: CurrentUser,
    version_id: UUID,
) -> tuple[dict[str, Any], AgentSessionView]:
    try:
        row = gateway.get_version(user.id, version_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    if not row.get("raw_extraction") or not row.get("agent_session"):
        raise HTTPException(status_code=409, detail={"code": "formulation_state_unavailable", "message": "This formulation has no resumable interpretation state."})
    view = AgentSessionView.model_validate(row["agent_session"])
    view.questions = [
        question for question in view.questions
        if question.question_type not in {"document_completeness", "ingredient_function"}
    ]
    for interpreted_row in view.interpreted_rows:
        interpreted_row.unresolved_fields = [
            uncertainty for uncertainty in interpreted_row.unresolved_fields
            if uncertainty.uncertainty_code != "ingredient_function"
        ]
    view.document_completeness_confirmed = True
    view.revision = row["revision"]
    _agent_service(request).restore(_parsed(row["raw_extraction"]), view)
    return row, view


@router.get("/me", response_model=CurrentUserView)
def me(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> CurrentUserView:
    try:
        return CurrentUserView.model_validate(gateway.me(user))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.delete("/me", status_code=204)
def delete_account(
    payload: PermanentDeleteRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> None:
    try:
        gateway.delete_account(user.id)
    except AccountDeletionBlockedError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "account_deletion_blocked_shared_workspace", "message": str(error)},
        ) from error
    except AccountDeletionError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "account_deletion_failed", "message": str(error)},
        ) from error


@router.get("/cases", response_model=list[CaseListItem])
def list_cases(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> list[CaseListItem]:
    return [_case(CaseListItem, item) for item in gateway.list_cases(user.id)]


@router.post("/cases", response_model=CaseView, status_code=201)
def create_case(
    payload: CaseCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> CaseView:
    try:
        row = gateway.create_case(user.id, payload.model_dump(mode="json", exclude_none=True))
        row["formulations"] = []
        return _case(CaseView, row)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/cases/{case_id}", response_model=CaseView)
def get_case(
    case_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> CaseView:
    try:
        return _case(CaseView, gateway.get_case(user.id, case_id))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.patch("/cases/{case_id}", response_model=CaseView)
def update_case(
    case_id: UUID,
    payload: CaseUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> CaseView:
    changes = payload.model_dump(mode="json", exclude_unset=True)
    try:
        row = gateway.update_case(user.id, case_id, changes)
        row["formulations"] = gateway.list_formulations(user.id, case_id)
        return _case(CaseView, row)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(
    case_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> None:
    try:
        gateway.delete_case(user.id, case_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except CaseDeletionError as error:
        raise HTTPException(status_code=503, detail={"code": "case_deletion_failed", "message": str(error)}) from error


@router.get("/cases/{case_id}/formulations", response_model=list[FormulationVersionSummary])
def list_formulations(
    case_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> list[FormulationVersionSummary]:
    try:
        return [_summary(item) for item in gateway.list_formulations(user.id, case_id)]
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.post("/cases/{case_id}/formulations", response_model=FormulationVersionView, status_code=201)
async def upload_formulation(
    case_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
    file: Annotated[UploadFile | None, File(description="Legacy single formulation file")] = None,
    files: Annotated[list[UploadFile] | None, File(description="Formulation and supporting documents")] = None,
) -> FormulationVersionView:
    uploads = ([file] if file is not None else []) + list(files or [])
    if not uploads or len(uploads) > 10:
        raise HTTPException(
            status_code=422,
            detail={"code": "document_batch_invalid", "message": "Upload between 1 and 10 documents."},
        )

    buffered: list[tuple[UploadFile, bytes, ParsedCSV | None]] = []
    parse_errors: list[tuple[UploadFile, CSVUploadError]] = []
    for upload in uploads:
        content = await upload.read(MAX_FILE_BYTES + 1)
        try:
            parsed_upload = parse_formulation_upload(
                upload.filename or "formulation.csv",
                content,
            )
        except CSVUploadError as error:
            parsed_upload = None
            parse_errors.append((upload, error))
        buffered.append((upload, content, parsed_upload))

    try:
        primary_index = select_primary_formulation(
            [item[2] for item in buffered],
            legacy_first_file=file is not None,
        )
    except DocumentBatchError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": error.code, "message": str(error)},
        ) from error

    primary_file, content, parsed = buffered[primary_index]
    if parsed is None:
        primary_error = next(error for upload, error in parse_errors if upload is primary_file)
        raise HTTPException(
            status_code=primary_error.status_code,
            detail={"code": primary_error.code, "message": str(primary_error)},
        )
    try:
        case = gateway.get_case(user.id, case_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error

    version_id = uuid4()
    storage_path = f"{case['organisation_id']}/{case_id}/{version_id}/{parsed.filename}"
    initial = AgentSessionView(
        session_id=str(version_id), revision=0, state=AgentSessionState.PARSING,
        filename=parsed.filename, source_format=parsed.source_format,
        model=_agent_service(request).model,
        activity=[AgentActivityItem(
            activity_id=str(uuid4()), status="complete",
            message=(
                f"Extracted {len(parsed.rows)} text lines from {parsed.page_count or 0} PDF page(s)"
                if parsed.source_format == "pdf" else f"Read {len(parsed.rows)} formulation rows"
            ),
        )],
    )
    gateway.upload_file(storage_path, content, primary_file.content_type)
    try:
        gateway.create_version(user.id, version_id, case_id, parsed.filename, storage_path, _raw(parsed), initial.model_dump(mode="json"))
    except Exception:
        gateway.remove_file(storage_path)
        raise
    try:
        view = _agent_service(request).create(parsed, session_id=str(version_id))
    except Exception as error:
        LOGGER.exception("Persistent formulation interpretation failed unexpectedly for version %s", version_id)
        initial.revision = 1
        initial.state = AgentSessionState.FAILED
        initial.error = AgentFailure(
            code="agent_interpretation_failed",
            message="Regulens could not complete the interpretation. Your uploaded file has been preserved.",
            recoverable=True,
        )
        initial.activity.append(AgentActivityItem(
            activity_id=str(uuid4()), status="error", message="Interpretation could not be completed",
        ))
        view = initial
    _persist(gateway, user, version_id, 0, view)

    supplier_service = SupplierDocumentService(gateway)
    supporting_failures: list[str] = []
    for index, (supporting_file, supporting_content, supporting_parsed) in enumerate(buffered):
        if index == primary_index:
            continue
        supporting_error = next(
            (error for upload, error in parse_errors if upload is supporting_file),
            None,
        )
        try:
            supplier_service.upload_and_attach(
                user_id=user.id,
                version_id=version_id,
                filename=supporting_file.filename or "supplier-document.pdf",
                content=supporting_content,
                content_type=supporting_file.content_type,
                preparsed=supporting_parsed,
                preparsed_error=supporting_error,
                process_immediately=False,
            )
        except CSVUploadError as error:
            supporting_failures.append(supporting_file.filename or "supporting document")
            LOGGER.warning(
                "Supporting document %s could not be attached to %s: %s",
                supporting_file.filename,
                version_id,
                error.code,
            )
        except Exception:
            supporting_failures.append(supporting_file.filename or "supporting document")
            LOGGER.exception(
                "Supporting document %s failed after formulation %s was preserved",
                supporting_file.filename,
                version_id,
            )
    _record_supporting_document_failures(
        gateway,
        user,
        version_id,
        view,
        supporting_failures,
    )
    return _view_from_row(gateway.get_version(user.id, version_id))


@router.get("/formulations/{version_id}", response_model=FormulationVersionView)
def get_formulation(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationVersionView:
    try:
        return _view_from_row(gateway.get_version(user.id, version_id))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/supplier-documents", response_model=list[SupplierDocumentView])
def list_supplier_documents(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
    search: Annotated[str | None, Query(max_length=200)] = None,
    include_archived: bool = False,
    available_only: bool = False,
) -> list[SupplierDocumentView]:
    rows = gateway.list_supplier_documents(
        user.id,
        include_archived=include_archived,
        available_only=available_only,
    )
    if search and (needle := " ".join(search.casefold().split())):
        searchable_fields = (
            "original_filename", "supplier_name", "trade_name", "product_code",
            "document_revision_label",
        )
        rows = [
            row for row in rows
            if any(needle in str(row.get(field) or "").casefold() for field in searchable_fields)
        ]
    return [_supplier_document(SupplierDocumentView, row) for row in rows]


@router.post(
    "/cases/{case_id}/supplier-documents",
    response_model=SupplierDocumentBatchView,
    status_code=201,
)
async def upload_case_supplier_documents(
    case_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
    files: Annotated[list[UploadFile], File(description="Standalone SDS/MSDS or supplier composition documents")],
) -> SupplierDocumentBatchView:
    if not files or len(files) > 10:
        raise HTTPException(
            status_code=422,
            detail={"code": "document_batch_invalid", "message": "Upload between 1 and 10 supplier documents."},
        )
    try:
        case = gateway.get_case(user.id, case_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error

    service = SupplierDocumentService(gateway)
    documents: list[SupplierDocumentView] = []
    failures: list[FormulationDocumentUploadFailure] = []
    for file in files:
        content = await file.read(MAX_FILE_BYTES + 1)
        try:
            document, _ = service.upload_to_library(
                user_id=user.id,
                organisation_id=UUID(str(case["organisation_id"])),
                filename=file.filename or "supplier-document.pdf",
                content=content,
                content_type=file.content_type,
                process_immediately=True,
            )
            documents.append(_supplier_document(SupplierDocumentView, document))
        except CSVUploadError as error:
            failures.append(FormulationDocumentUploadFailure(
                filename=file.filename or "supplier-document.pdf",
                code=error.code,
                message=str(error),
                recoverable=error.code == "agent_pdf_text_unavailable",
            ))
        except Exception:
            LOGGER.exception("Standalone supplier document %s could not be retained", file.filename)
            failures.append(FormulationDocumentUploadFailure(
                filename=file.filename or "supplier-document.pdf",
                code="document_upload_failed",
                message="The private supplier source could not be stored. Other documents in this batch were preserved.",
                recoverable=True,
            ))
    return SupplierDocumentBatchView(documents=documents, failures=failures)


@router.get("/supplier-documents/{document_id}", response_model=SupplierDocumentDetailView)
def get_supplier_document(
    document_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> SupplierDocumentDetailView:
    try:
        return _supplier_document(
            SupplierDocumentDetailView,
            gateway.get_supplier_document_detail(user.id, document_id),
        )
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/supplier-documents/{document_id}/file", response_model=SignedFileView)
def get_supplier_document_file(
    document_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> SignedFileView:
    try:
        return SignedFileView(
            url=gateway.signed_supplier_document_url(user.id, document_id),
            expires_in=60,
        )
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.patch("/supplier-documents/{document_id}", response_model=SupplierDocumentView)
def update_supplier_document(
    document_id: UUID,
    payload: SupplierDocumentUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> SupplierDocumentView:
    changes = payload.model_dump(mode="json", exclude={"revision"}, exclude_unset=True)
    try:
        row = SupplierDocumentService(gateway).confirm_library_metadata(
            user_id=user.id,
            document_id=document_id,
            expected_revision=payload.revision,
            changes=changes,
        )
        return _supplier_document(SupplierDocumentView, row)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except RevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "supplier_document_revision_conflict", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "supplier_document_update_invalid", "message": str(error)},
        ) from error


@router.delete("/supplier-documents/{document_id}", status_code=204)
def delete_supplier_document(
    document_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> None:
    try:
        gateway.delete_supplier_document(user.id, document_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except SupplierDocumentDeletionError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "supplier_document_deletion_blocked", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "supplier_document_update_invalid", "message": str(error)},
        ) from error


@router.post("/supplier-documents/{document_id}/retry", response_model=SupplierDocumentView)
def retry_supplier_document(
    document_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> SupplierDocumentView:
    try:
        document = SupplierDocumentService(gateway).retry_processing(
            user_id=user.id,
            document_id=document_id,
            vision_extractor=getattr(request.app.state, "document_vision_extractor", None),
            text_extractor=getattr(request.app.state, "document_text_extractor", None),
        )
        return _supplier_document(SupplierDocumentView, document)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except SupplierDocumentProcessingError as error:
        raise HTTPException(
            status_code=503 if error.recoverable else 422,
            detail={"code": error.code, "message": str(error), "recoverable": error.recoverable},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "supplier_document_retry_invalid", "message": str(error)},
        ) from error


@router.get(
    "/formulations/{version_id}/documents",
    response_model=list[FormulationDocumentView],
)
def list_formulation_documents(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> list[FormulationDocumentView]:
    try:
        return [
            _formulation_document(row)
            for row in gateway.list_formulation_documents(user.id, version_id)
        ]
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.post(
    "/formulations/{version_id}/documents",
    response_model=FormulationDocumentBatchView,
    status_code=201,
)
async def upload_formulation_documents(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
    files: Annotated[list[UploadFile], File(description="Supplier or supporting documents")],
) -> FormulationDocumentBatchView:
    if not files or len(files) > 10:
        raise HTTPException(
            status_code=422,
            detail={"code": "document_batch_invalid", "message": "Upload between 1 and 10 documents."},
        )
    service = SupplierDocumentService(gateway)
    attachments: list[FormulationDocumentView] = []
    failures: list[FormulationDocumentUploadFailure] = []
    for file in files:
        content = await file.read(MAX_FILE_BYTES + 1)
        try:
            row, _ = service.upload_and_attach(
                user_id=user.id,
                version_id=version_id,
                filename=file.filename or "supplier-document.pdf",
                content=content,
                content_type=file.content_type,
                process_immediately=False,
            )
            attachments.append(_formulation_document(row))
        except CSVUploadError as error:
            failures.append(FormulationDocumentUploadFailure(
                filename=file.filename or "supplier-document.pdf",
                code=error.code,
                message=str(error),
                recoverable=False,
            ))
        except ResourceNotFoundError as error:
            raise _not_found(error) from error
        except Exception:
            LOGGER.exception("Supporting document %s could not be retained", file.filename)
            failures.append(FormulationDocumentUploadFailure(
                filename=file.filename or "supplier-document.pdf",
                code="document_upload_failed",
                message="The private source could not be stored. Other documents in this batch were preserved.",
                recoverable=True,
            ))
    return FormulationDocumentBatchView(documents=attachments, failures=failures)


@router.post(
    "/formulations/{version_id}/documents/attach",
    response_model=FormulationDocumentView,
    status_code=201,
)
def attach_supplier_document(
    version_id: UUID,
    payload: AttachSupplierDocumentRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationDocumentView:
    try:
        document = gateway.get_supplier_document_detail(user.id, payload.supplier_document_id)
        if document.get("library_status") != "available":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "supplier_document_not_ready",
                    "message": "Confirm this supplier document before attaching it to another formulation.",
                },
            )
        service = SupplierDocumentService(gateway)
        vision_extractor = getattr(request.app.state, "document_vision_extractor", None)
        text_extractor = getattr(request.app.state, "document_text_extractor", None)
        if not service.extraction_is_compatible(
            document,
            vision_extractor=vision_extractor,
            text_extractor=text_extractor,
        ):
            document = service.retry_processing(
                user_id=user.id,
                document_id=payload.supplier_document_id,
                vision_extractor=vision_extractor,
                text_extractor=text_extractor,
            )
        return _formulation_document(gateway.attach_supplier_document(
            user.id,
            version_id,
            payload.supplier_document_id,
        ))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except SupplierDocumentProcessingError as error:
        raise HTTPException(
            status_code=503 if error.recoverable else 422,
            detail={"code": error.code, "message": str(error), "recoverable": error.recoverable},
        ) from error


@router.get("/formulation-documents/{document_id}", response_model=FormulationDocumentView)
def get_formulation_document(
    document_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationDocumentView:
    try:
        return _formulation_document(gateway.get_formulation_document(user.id, document_id))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.patch("/formulation-documents/{document_id}", response_model=FormulationDocumentView)
def update_formulation_document(
    document_id: UUID,
    payload: FormulationDocumentUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationDocumentView:
    try:
        row = gateway.update_formulation_document(
            user.id,
            document_id,
            expected_revision=payload.revision,
            changes=payload.model_dump(mode="json", exclude={"revision"}, exclude_unset=True),
        )
        return _formulation_document(row)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except RevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "formulation_document_revision_conflict", "message": str(error)},
        ) from error


@router.post(
    "/formulation-documents/{document_id}/interpret",
    response_model=FormulationDocumentView,
)
def interpret_formulation_document(
    document_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationDocumentView:
    """Idempotently process one retained source document.

    Upload and interpretation are deliberately separate so a multi-document
    upload returns quickly.  A completed compatible extraction is returned as
    is; an uploaded or stale document is processed from its private source.
    """
    attachment: dict[str, Any] | None = None
    try:
        attachment = gateway.get_formulation_document(user.id, document_id)
        supplier_document_id = attachment.get("supplier_document_id")
        if not supplier_document_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "document_interpret_source_unavailable",
                    "message": "This document has no saved private source to interpret.",
                },
            )
        supplier_document = gateway.get_supplier_document_detail(
            user.id,
            UUID(str(supplier_document_id)),
        )
        service = SupplierDocumentService(gateway)
        vision_extractor = getattr(request.app.state, "document_vision_extractor", None)
        text_extractor = getattr(request.app.state, "document_text_extractor", None)
        if (
            attachment.get("processing_status") in {"ready", "needs_confirmation"}
            and service.extraction_is_compatible(
                supplier_document,
                vision_extractor=vision_extractor,
                text_extractor=text_extractor,
            )
        ):
            return _formulation_document(attachment)
        service.retry_processing(
            user_id=user.id,
            document_id=UUID(str(supplier_document_id)),
            vision_extractor=vision_extractor,
            text_extractor=text_extractor,
        )
        refreshed = gateway.refresh_formulation_document_from_supplier(
            user.id,
            document_id,
            expected_revision=int(attachment["revision"]),
        )
        return _formulation_document(refreshed)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except RevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "formulation_document_revision_conflict", "message": str(error)},
        ) from error
    except SupplierDocumentProcessingError as error:
        if attachment is not None:
            try:
                gateway.refresh_formulation_document_from_supplier(
                    user.id,
                    document_id,
                    expected_revision=int(attachment["revision"]),
                )
            except (ResourceNotFoundError, RevisionConflictError, ValueError):
                LOGGER.warning(
                    "Could not refresh failed supplier-document snapshot %s",
                    document_id,
                    exc_info=True,
                )
        raise HTTPException(
            status_code=503 if error.recoverable else 422,
            detail={"code": error.code, "message": str(error), "recoverable": error.recoverable},
        ) from error


@router.post(
    "/formulation-documents/{document_id}/retry",
    response_model=FormulationDocumentView,
)
def retry_formulation_document(
    document_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationDocumentView:
    """Retry a retained source and refresh only this formulation's snapshot."""
    attachment: dict[str, Any] | None = None
    try:
        attachment = gateway.get_formulation_document(user.id, document_id)
        supplier_document_id = attachment.get("supplier_document_id")
        if not supplier_document_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "document_retry_source_unavailable",
                    "message": "This document has no saved private source to retry.",
                },
            )
        SupplierDocumentService(gateway).retry_processing(
            user_id=user.id,
            document_id=UUID(str(supplier_document_id)),
            vision_extractor=getattr(request.app.state, "document_vision_extractor", None),
            text_extractor=getattr(request.app.state, "document_text_extractor", None),
        )
        refreshed = gateway.refresh_formulation_document_from_supplier(
            user.id,
            document_id,
            expected_revision=int(attachment["revision"]),
        )
        return _formulation_document(refreshed)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except RevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "formulation_document_revision_conflict", "message": str(error)},
        ) from error
    except SupplierDocumentProcessingError as error:
        if attachment is not None:
            try:
                gateway.refresh_formulation_document_from_supplier(
                    user.id,
                    document_id,
                    expected_revision=int(attachment["revision"]),
                )
            except (ResourceNotFoundError, RevisionConflictError, ValueError):
                LOGGER.warning(
                    "Could not refresh failed supplier-document snapshot %s",
                    document_id,
                    exc_info=True,
                )
        raise HTTPException(
            status_code=503 if error.recoverable else 422,
            detail={"code": error.code, "message": str(error), "recoverable": error.recoverable},
        ) from error


@router.delete("/formulations/{version_id}/documents/{document_id}", status_code=204)
def detach_formulation_document(
    version_id: UUID,
    document_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> None:
    try:
        gateway.detach_formulation_document(user.id, version_id, document_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


def _assembly_runtime(request: Request):
    store = getattr(request.app.state, "regulatory_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "regulatory_data_unavailable", "message": "Regulatory data is unavailable."},
        )
    return (
        store,
        getattr(request.app.state, "ingredient_catalog", None),
        getattr(request.app.state, "ingredient_linkage", None),
    )


def _merge_assembly_state(
    existing: FormulationAssemblyState | None,
    discovered: FormulationAssemblyState,
) -> FormulationAssemblyState:
    if existing is None:
        return discovered
    existing_materials = {item.material_id: item for item in existing.materials}

    def merge_material(discovered_material):
        previous = existing_materials.get(discovered_material.material_id)
        if previous is None:
            return discovered_material
        previous_constituents = {
            item.constituent_id: item for item in previous.constituents
        }
        removed_constituent_ids = set(previous.removed_constituent_ids)
        merged_constituents = []
        for source_item in discovered_material.constituents:
            if source_item.constituent_id in removed_constituent_ids:
                continue
            prior_item = previous_constituents.get(source_item.constituent_id)
            if prior_item is not None and prior_item.user_edits:
                merged_constituents.append(prior_item)
            else:
                merged_constituents.append(source_item)
        discovered_ids = {
            item.constituent_id for item in discovered_material.constituents
        }
        merged_constituents.extend(
            item for item in previous.constituents
            if item.constituent_id not in discovered_ids
            and item.constituent_id not in removed_constituent_ids
            and item.user_edits.get("added_by_reviewer") is True
        )
        return discovered_material.model_copy(update={
            # Prefer an explicit retained reviewer value, but do not let a
            # stale empty snapshot erase usage now found in the formulation.
            "finished_product_usage": (
                previous.finished_product_usage
                or discovered_material.finished_product_usage
            ),
            "disclosure_status": previous.disclosure_status,
            "confirmation_status": previous.confirmation_status,
            "constituents": merged_constituents,
            "removed_constituent_ids": sorted(removed_constituent_ids),
        })

    return discovered.model_copy(update={
        "materials": [
            merge_material(item) for item in discovered.materials
        ],
        # Direct rows are rediscovered from the currently attached documents
        # and primary Agent state. Keeping rows from a detached source would
        # silently screen data whose evidence is no longer active.
        "direct_ingredients": discovered.direct_ingredients,
        "formulation_name": existing.formulation_name or discovered.formulation_name,
        "product_context": existing.product_context,
        "product_applicability": existing.product_applicability,
        "source_document_ids": sorted(set(
            discovered.source_document_ids
        )),
        "source_document_snapshots": discovered.source_document_snapshots,
        "source_document_metadata": discovered.source_document_metadata,
    })


def _prepare_and_persist_assembly(
    *,
    request: Request,
    gateway: SupabaseGateway,
    user: CurrentUser,
    row: dict[str, Any],
    state: FormulationAssemblyState,
    expected_revision: int,
) -> AssemblyPreparationView:
    store, catalogue, linkages = _assembly_runtime(request)
    normalized, prepared = prepare_trade_name_assembly(
        assembly_revision=expected_revision + 1,
        state=state,
        formulation_id=str(row["id"]),
        source_filename=row.get("original_filename"),
        store=store,
        catalogue=catalogue,
        linkages=linkages,
    )
    persisted = gateway.persist_assembly(
        user.id,
        UUID(str(row["id"])),
        expected_assembly_revision=expected_revision,
        assembly_state=normalized.model_dump(mode="json"),
        calculation_snapshot=prepared.result.calculation_snapshot,
        canonical_formulation=(
            prepared.formulation.model_dump(mode="json") if prepared.formulation else None
        ),
    )
    return AssemblyPreparationView(
        assembly_revision=int(persisted.get("assembly_revision", expected_revision + 1)),
        state=normalized,
        assembly=prepared.result,
        formulation=(prepared.formulation.model_dump(mode="json") if prepared.formulation else None),
    )


@router.get(
    "/formulations/{version_id}/assembly",
    response_model=AssemblyPreparationView,
)
def get_formulation_assembly(
    version_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AssemblyPreparationView:
    """Restore persisted reviewer state without mutating its revision.

    The calculation is deterministic and cheap. Recomputing the response from
    persisted assembly state keeps the response schema complete while avoiding
    a database write, extraction call or AI call on ordinary page reloads.
    """
    try:
        row = gateway.get_version(user.id, version_id)
        raw_state = row.get("assembly_state")
        if not raw_state:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "assembly_not_initialized",
                    "message": "Material assembly has not been prepared yet.",
                },
            )
        state = FormulationAssemblyState.model_validate(raw_state)
        store, catalogue, linkages = _assembly_runtime(request)
        normalized, prepared = prepare_trade_name_assembly(
            assembly_revision=int(row.get("assembly_revision") or 0),
            state=state,
            formulation_id=str(row["id"]),
            source_filename=row.get("original_filename"),
            store=store,
            catalogue=catalogue,
            linkages=linkages,
        )
        return AssemblyPreparationView(
            assembly_revision=int(row.get("assembly_revision") or 0),
            state=normalized,
            assembly=prepared.result,
            formulation=(
                prepared.formulation.model_dump(mode="json")
                if prepared.formulation else None
            ),
        )
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.post(
    "/formulations/{version_id}/assembly/refresh",
    response_model=AssemblyPreparationView,
)
def refresh_formulation_assembly(
    version_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AssemblyPreparationView:
    """Discover attached sources and create/update canonical assembly state."""
    try:
        row = gateway.get_version(user.id, version_id)
        store, catalogue, linkages = _assembly_runtime(request)
        agent_state = row.get("agent_session") or row.get("agent_state")
        session_name = None
        if isinstance(agent_state, dict):
            name_field = agent_state.get("formulation_name") or {}
            session_name = name_field.get("value") if isinstance(name_field, dict) else None
        discovered = derive_assembly_state(
            version_id=str(version_id),
            formulation_name=session_name or row.get("original_filename"),
            agent_state=agent_state,
            documents=gateway.list_formulation_documents(user.id, version_id),
            store=store,
            catalogue=catalogue,
            linkages=linkages,
        )
        existing = (
            FormulationAssemblyState.model_validate(row["assembly_state"])
            if row.get("assembly_state") else None
        )
        state = _merge_assembly_state(existing, discovered)
        return _prepare_and_persist_assembly(
            request=request,
            gateway=gateway,
            user=user,
            row=row,
            state=state,
            expected_revision=int(row.get("assembly_revision") or 0),
        )
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except RevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "assembly_revision_conflict", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "assembly_input_invalid", "message": str(error)},
        ) from error


@router.patch(
    "/formulations/{version_id}/assembly",
    response_model=AssemblyPreparationView,
)
def update_formulation_assembly(
    version_id: UUID,
    payload: AssemblyStateUpdate,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AssemblyPreparationView:
    """Persist reviewer edits and deterministically recalculate contributions."""
    try:
        row = gateway.get_version(user.id, version_id)
        if int(row.get("assembly_revision") or 0) != payload.assembly_revision:
            raise RevisionConflictError("The formulation assembly changed; reload before continuing")
        return _prepare_and_persist_assembly(
            request=request,
            gateway=gateway,
            user=user,
            row=row,
            state=payload.assembly_state,
            expected_revision=payload.assembly_revision,
        )
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except RevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "assembly_revision_conflict", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "assembly_input_invalid", "message": str(error)},
        ) from error


@router.patch("/formulations/{version_id}", response_model=FormulationVersionView)
def patch_formulation(
    version_id: UUID,
    payload: FormulationVersionPatch,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationVersionView:
    try:
        return _view_from_row(gateway.patch_version(user.id, version_id, payload.revision, payload.product_context))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "agent_revision_conflict", "message": str(error)}) from error


@router.delete("/formulations/{version_id}", status_code=204)
def delete_formulation(
    version_id: UUID,
    payload: PermanentDeleteRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> None:
    try:
        gateway.delete_formulation(user.id, version_id)
        service = getattr(request.app.state, "formulation_agent", None)
        if service is not None:
            service.forget(str(version_id))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except FormulationDeletionError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "formulation_deletion_failed", "message": str(error)},
        ) from error


@router.post("/formulations/{version_id}/interpret", response_model=FormulationVersionView)
def retry_interpretation(
    version_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationVersionView:
    row, view = _hydrate(request, gateway, user, version_id)
    result = _agent_service(request).retry(view.session_id)
    _persist(gateway, user, version_id, row["revision"], result)
    return _view_from_row(gateway.get_version(user.id, version_id))


@router.post("/formulations/{version_id}/answers", response_model=FormulationVersionView)
def answer_questions(
    version_id: UUID,
    payload: AgentAnswersRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FormulationVersionView:
    row, view = _hydrate(request, gateway, user, version_id)
    if payload.revision != row["revision"]:
        raise HTTPException(status_code=409, detail={"code": "agent_revision_conflict", "message": "The formulation changed; reload before continuing."})
    try:
        result = _agent_service(request).apply_answers(view.session_id, payload)
    except AgentRevisionConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "agent_revision_conflict", "message": str(error)}) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "agent_answer_invalid", "message": str(error)}) from error
    _persist(gateway, user, version_id, row["revision"], result)
    return _view_from_row(gateway.get_version(user.id, version_id))


@router.post("/formulations/{version_id}/prepare", response_model=AgentPreparedFormulation)
def prepare_formulation(
    version_id: UUID,
    payload: AgentPrepareRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AgentPreparedFormulation:
    row, view = _hydrate(request, gateway, user, version_id)
    if payload.revision != row["revision"]:
        raise HTTPException(status_code=409, detail={"code": "agent_revision_conflict", "message": "The formulation changed; reload before continuing."})
    supporting_documents = gateway.list_formulation_documents(user.id, version_id)
    excluded_row_ids: set[str] = set()
    formulation_override: FormulationRequest | None = None
    assembly_revision = int(row.get("assembly_revision") or 0)
    if any(document.get("extraction_result") for document in supporting_documents):
        assembly = refresh_formulation_assembly(version_id, request, user, gateway)
        assembly_revision = assembly.assembly_revision
        if assembly.formulation is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "formulation_assembly_blocked",
                    "message": "Resolve the source-document and material checks before screening.",
                },
            )
        excluded_row_ids = {
            item.row_id
            for item in assembly.state.formulation_row_ownership
            if item.owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
        }
        assembled_formulation = FormulationRequest.model_validate(assembly.formulation)
        formulation_override = assembled_formulation.model_copy(update={
            "formulation_id": payload.formulation_id or assembled_formulation.formulation_id,
            "formulation_name": payload.formulation_name or assembled_formulation.formulation_name,
            "product_context": payload.product_context,
            "product_applicability": payload.product_applicability,
        })
    try:
        prepared = _agent_service(request).prepare(
            view.session_id,
            payload,
            excluded_row_ids=excluded_row_ids,
            formulation_override=formulation_override,
        )
    except (AgentRevisionConflictError, AgentConfirmationRequiredError) as error:
        raise HTTPException(status_code=409, detail={"code": "agent_confirmation_required", "message": str(error)}) from error
    formulation = prepared.formulation.model_copy(update={
        "input_revision": ScreeningInputRevision(
            agent_revision=prepared.session.revision,
            assembly_revision=assembly_revision,
        ),
    })
    prepared = prepared.model_copy(update={
        "formulation": formulation,
        "session": prepared.session.model_copy(update={
            "canonical_formulation": formulation,
        }),
    })
    _persist(gateway, user, version_id, row["revision"], prepared.session)
    return prepared


@router.post("/formulations/{version_id}/screen", response_model=ScreeningRunView, status_code=201)
def screen_persistent_formulation(
    version_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> ScreeningRunView:
    try:
        row = gateway.get_version(user.id, version_id)
        supporting_documents = gateway.list_formulation_documents(user.id, version_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    pending_documents = [
        document for document in supporting_documents
        if document.get("processing_status") in {
            "uploaded", "parsing", "classifying", "extracting", "interrupted", "failed",
        }
    ]
    if pending_documents:
        names = ", ".join(str(item.get("original_filename") or "supporting document") for item in pending_documents[:3])
        raise HTTPException(
            status_code=409,
            detail={
                "code": "supporting_documents_not_ready",
                "message": (
                    f"Finish, retry or detach the retained supporting document(s) before screening: {names}."
                ),
            },
        )
    if not row.get("canonical_formulation"):
        raise HTTPException(status_code=409, detail={"code": "formulation_not_ready", "message": "Prepare the formulation before screening."})
    formulation = FormulationRequest.model_validate(row["canonical_formulation"])
    if (
        any(document.get("extraction_result") for document in supporting_documents)
        and formulation.assembly_scope is None
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "formulation_assembly_not_prepared",
                "message": "Source information changed. Review the highlighted input and run screening again.",
            },
        )
    store = request.app.state.regulatory_store
    if store is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "accepted_baseline_integrity_failure", "message": request.app.state.baseline_error or "Accepted regulatory baseline is unavailable."},
        )
    try:
        deterministic = screen_formulation(
            store, formulation,
            ingredient_catalog=request.app.state.ingredient_catalog,
            linkage_store=getattr(request.app.state, "ingredient_linkage", None),
            linkage_error=getattr(request.app.state, "identity_linkage_error", None),
            catalogue_error=request.app.state.identity_catalogue_error,
        )
    except UnsupportedProductContextError as error:
        raise HTTPException(status_code=422, detail={"code": "unsupported_product_context", "message": str(error)}) from error
    explanation_service = request.app.state.review_explanation_service
    try:
        result = explanation_service.enrich(deterministic)
    except Exception:
        result = explanation_service.fallback_only(deterministic)
    saved = gateway.insert_screening(
        user.id, version_id, store.dataset_version, "Singapore",
        formulation.model_dump(mode="json"), result.model_dump(mode="json"),
    )
    return _screening(saved, row)


@router.get("/formulations/{version_id}/screenings", response_model=list[ScreeningRunView])
def list_screenings(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> list[ScreeningRunView]:
    try:
        version = gateway.get_version(user.id, version_id)
        return [
            _screening(item, version)
            for item in gateway.list_screenings(user.id, version_id)
        ]
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/screenings/{screening_id}", response_model=ScreeningRunView)
def get_screening(
    screening_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> ScreeningRunView:
    try:
        row = gateway.get_screening(user.id, screening_id)
        version = gateway.get_version(user.id, row["formulation_version_id"])
        return _screening(row, version)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/screenings/{screening_id}/report.pdf", response_class=StreamingResponse)
def screening_report(
    screening_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> StreamingResponse:
    try:
        saved = gateway.get_screening(user.id, screening_id)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    response = FormulationScreeningResponse.model_validate(saved["result_snapshot"])
    screened_at = datetime.fromisoformat(str(saved["created_at"]).replace("Z", "+00:00"))
    return StreamingResponse(
        BytesIO(build_screening_report(
            response,
            jurisdiction=saved["jurisdiction"],
            screening_reference=str(saved["id"]),
            screened_at=screened_at,
        )),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{screening_report_filename(response)}"'
        },
    )


@router.get("/formulations/{version_id}/file", response_model=SignedFileView)
def formulation_file(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> SignedFileView:
    try:
        return SignedFileView(url=gateway.signed_file_url(user.id, version_id), expires_in=60)
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


def _required_agent_session(version: FormulationVersionView) -> AgentSessionView:
    if version.agent_session is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "formulation_state_unavailable", "message": "This formulation has no resumable interpretation state."},
        )
    return version.agent_session


@persistent_agent_router.post("", response_model=AgentSessionView, status_code=201)
async def upload_formulation_compatibility_alias(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
    case_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File(description="Formulation file")],
) -> AgentSessionView:
    return _required_agent_session(await upload_formulation(case_id, request, user, gateway, file))


@persistent_agent_router.get("/{version_id}", response_model=AgentSessionView)
def get_formulation_compatibility_alias(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AgentSessionView:
    try:
        return _required_agent_session(_view_from_row(gateway.get_version(user.id, version_id)))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@persistent_agent_router.post("/{version_id}/retry", response_model=AgentSessionView)
def retry_formulation_compatibility_alias(
    version_id: UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AgentSessionView:
    return _required_agent_session(retry_interpretation(version_id, request, user, gateway))


@persistent_agent_router.post("/{version_id}/answers", response_model=AgentSessionView)
def answer_formulation_compatibility_alias(
    version_id: UUID,
    payload: AgentAnswersRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AgentSessionView:
    return _required_agent_session(answer_questions(version_id, payload, request, user, gateway))


@persistent_agent_router.post("/{version_id}/prepare", response_model=AgentPreparedFormulation)
def prepare_formulation_compatibility_alias(
    version_id: UUID,
    payload: AgentPrepareRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> AgentPreparedFormulation:
    return prepare_formulation(version_id, payload, request, user, gateway)


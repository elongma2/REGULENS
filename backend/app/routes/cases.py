from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
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
    PermanentDeleteRequest,
    ScreeningRunView,
    SignedFileView,
)
from backend.app.models.formulation import FormulationRequest, FormulationScreeningResponse
from backend.app.services.agent_csv import CSVUploadError, MAX_FILE_BYTES, ParsedCSV, parse_formulation_upload
from backend.app.services.formulation import screen_formulation
from backend.app.services.formulation_agent import (
    AgentConfirmationRequiredError,
    AgentRevisionConflictError,
    FormulationAgentService,
)
from backend.app.services.parsing import UnsupportedProductContextError
from backend.app.services.screening_report import build_screening_report, screening_report_filename
from backend.app.services.supabase_gateway import (
    AccountDeletionBlockedError,
    AccountDeletionError,
    CaseDeletionError,
    FormulationDeletionError,
    ResourceNotFoundError,
    RevisionConflictError,
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
    )


def _raw(parsed: ParsedCSV) -> dict[str, Any]:
    return {"filename": parsed.filename, "delimiter": parsed.delimiter, "rows": [list(row) for row in parsed.rows]}


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
        source = row.concentration.value.source_value if row.concentration.value else None
        proposed = row.concentration.unit.value if field == "concentration.unit" and row.concentration.unit else (
            row.concentration.value.value if row.concentration.value else None
        )
        return source, proposed
    if field == "preparation_stage" and row.concentration and row.concentration.preparation_stage:
        return row.concentration.preparation_stage.source_value, row.concentration.preparation_stage.value
    return None, None


def _clarifications(view: AgentSessionView) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for question in view.questions:
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
    return FormulationVersionView.model_validate({
        key: value for key, value in row.items() if key in FormulationVersionView.model_fields
    })


def _summary(row: dict[str, Any]) -> FormulationVersionSummary:
    return FormulationVersionSummary.model_validate({
        key: value for key, value in row.items() if key in FormulationVersionSummary.model_fields
    })


def _case(model: type[CaseView] | type[CaseListItem], row: dict[str, Any]) -> CaseView | CaseListItem:
    return model.model_validate({key: value for key, value in row.items() if key in model.model_fields})


def _screening(row: dict[str, Any]) -> ScreeningRunView:
    return ScreeningRunView.model_validate({
        key: value for key, value in row.items() if key in ScreeningRunView.model_fields
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
    file: Annotated[UploadFile, File(description="Formulation file")],
) -> FormulationVersionView:
    content = await file.read(MAX_FILE_BYTES + 1)
    try:
        parsed = parse_formulation_upload(file.filename or "formulation.csv", content)
        case = gateway.get_case(user.id, case_id)
    except CSVUploadError as error:
        raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error)}) from error
    except ResourceNotFoundError as error:
        raise _not_found(error) from error

    version_id = uuid4()
    storage_path = f"{case['organisation_id']}/{case_id}/{version_id}/{parsed.filename}"
    initial = AgentSessionView(
        session_id=str(version_id), revision=0, state=AgentSessionState.PARSING,
        filename=parsed.filename, model=_agent_service(request).model,
        activity=[AgentActivityItem(activity_id=str(uuid4()), status="complete", message=f"Read {len(parsed.rows)} formulation rows")],
    )
    gateway.upload_file(storage_path, content, file.content_type)
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
    try:
        prepared = _agent_service(request).prepare(view.session_id, payload)
    except (AgentRevisionConflictError, AgentConfirmationRequiredError) as error:
        raise HTTPException(status_code=409, detail={"code": "agent_confirmation_required", "message": str(error)}) from error
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
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    if not row.get("canonical_formulation"):
        raise HTTPException(status_code=409, detail={"code": "formulation_not_ready", "message": "Prepare the formulation before screening."})
    formulation = FormulationRequest.model_validate(row["canonical_formulation"])
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
    return _screening(saved)


@router.get("/formulations/{version_id}/screenings", response_model=list[ScreeningRunView])
def list_screenings(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> list[ScreeningRunView]:
    try:
        return [_screening(item) for item in gateway.list_screenings(user.id, version_id)]
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/screenings/{screening_id}", response_model=ScreeningRunView)
def get_screening(
    screening_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> ScreeningRunView:
    try:
        return _screening(gateway.get_screening(user.id, screening_id))
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


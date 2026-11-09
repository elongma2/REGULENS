from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from .agent import AgentSessionView
from .document_intake import (
    AssemblyResult,
    DocumentProcessingStatus,
    DocumentRole,
    FormulationAssemblyState,
    SupplierDocumentLibraryStatus,
)
from .formulation import FormulationScreeningResponse
from .screening import StrictModel


CaseStatus = Literal["active", "archived"]
FormulationVersionStatus = Literal[
    "uploaded", "interpreting", "clarification_required", "interpreted",
    "ready_to_screen", "screened", "failed",
]


class CurrentUserView(StrictModel):
    id: UUID
    email: str | None = None
    display_name: str
    default_organisation_id: UUID
    organisations: list[dict[str, Any]] = Field(default_factory=list)


class CaseCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    organisation_id: UUID | None = None


class CaseUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    product_type: str | None = Field(default=None, max_length=200)
    status: CaseStatus | None = None


class FormulationVersionSummary(StrictModel):
    id: UUID
    case_id: UUID
    version_number: int
    original_filename: str | None = None
    status: FormulationVersionStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    screening_count: int = 0


class CaseView(StrictModel):
    id: UUID
    organisation_id: UUID
    name: str
    client_name: str | None = None
    product_type: str | None = None
    status: CaseStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    formulations: list[FormulationVersionSummary] = Field(default_factory=list)


class CaseReviewSummary(StrictModel):
    latest_screening_run_id: UUID | None = None
    latest_screening_formulation_version_id: UUID | None = None
    latest_screening_at: datetime | None = None
    attention_results: int = 0
    reviewer_items_remaining: int = 0
    open_follow_ups: int = 0
    unresolved_clarifications: int = 0
    last_review_activity_at: datetime | None = None


class CaseListItem(CaseView):
    latest_formulation: FormulationVersionSummary | None = None
    latest_finding_count: int | None = None
    review_summary: CaseReviewSummary | None = None


class FormulationVersionPatch(StrictModel):
    revision: int = Field(ge=0)
    product_context: dict[str, Any] | None = None


class FormulationVersionView(FormulationVersionSummary):
    raw_extraction: dict[str, Any] | None = None
    agent_session: AgentSessionView | None = None
    canonical_formulation: dict[str, Any] | None = None
    product_context: dict[str, Any] | None = None
    assembly_state: dict[str, Any] | None = None
    assembly_revision: int = 0
    calculation_snapshot: dict[str, Any] | None = None


class SupplierDocumentView(StrictModel):
    id: UUID
    organisation_id: UUID
    original_filename: str
    mime_type: str
    sha256: str
    page_count: int | None = None
    supplier_name: str | None = None
    trade_name: str | None = None
    product_code: str | None = None
    document_revision_label: str | None = None
    document_date: str | None = None
    supersedes_supplier_document_id: UUID | None = None
    detected_roles: list[dict[str, Any]] = Field(default_factory=list)
    confirmed_roles: list[DocumentRole] = Field(default_factory=list)
    extraction_schema_version: str | None = None
    processing_status: DocumentProcessingStatus
    library_status: SupplierDocumentLibraryStatus
    processing_diagnostics: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    processing_key: str | None = None
    processing_attempt: int = 0
    revision: int
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SupplierDocumentDetailView(SupplierDocumentView):
    parsed_content: dict[str, Any] | None = None
    extraction_result: dict[str, Any] | None = None
    model_configuration: str | None = None


class SupplierDocumentUpdate(StrictModel):
    revision: int = Field(ge=0)
    supplier_name: str | None = Field(default=None, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    product_code: str | None = Field(default=None, max_length=200)
    document_revision_label: str | None = Field(default=None, max_length=200)
    supersedes_supplier_document_id: UUID | None = None
    confirmed_roles: list[DocumentRole] | None = None
    library_status: Literal["available", "needs_confirmation", "archived"] | None = None


class FormulationDocumentView(StrictModel):
    id: UUID
    formulation_version_id: UUID
    supplier_document_id: UUID | None = None
    original_filename: str
    mime_type: str
    sha256: str
    page_count: int | None = None
    processing_status: DocumentProcessingStatus
    detected_roles: list[dict[str, Any]] = Field(default_factory=list)
    confirmed_roles: list[DocumentRole] = Field(default_factory=list)
    parsed_content: dict[str, Any] | None = None
    extraction_result: dict[str, Any] | None = None
    processing_diagnostics: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    document_revision_label: str | None = None
    governing_for_material: bool = False
    attached_extraction_key: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime


class FormulationDocumentUploadFailure(StrictModel):
    filename: str
    code: str
    message: str
    recoverable: bool = False


class FormulationDocumentBatchView(StrictModel):
    documents: list[FormulationDocumentView] = Field(default_factory=list)
    failures: list[FormulationDocumentUploadFailure] = Field(default_factory=list)


class SupplierDocumentBatchView(StrictModel):
    documents: list[SupplierDocumentView] = Field(default_factory=list)
    failures: list[FormulationDocumentUploadFailure] = Field(default_factory=list)


class AttachSupplierDocumentRequest(StrictModel):
    supplier_document_id: UUID


class FormulationDocumentUpdate(StrictModel):
    revision: int = Field(ge=0)
    confirmed_roles: list[DocumentRole] | None = None
    governing_for_material: bool | None = None
    document_revision_label: str | None = Field(default=None, max_length=200)


class AssemblyStateUpdate(StrictModel):
    assembly_revision: int = Field(ge=0)
    assembly_state: FormulationAssemblyState


class AssemblyPreparationView(StrictModel):
    assembly_revision: int = Field(ge=0)
    state: FormulationAssemblyState
    assembly: AssemblyResult
    formulation: dict[str, Any] | None = None


class ScreeningRunView(StrictModel):
    id: UUID
    formulation_version_id: UUID
    regulatory_dataset_id: str
    jurisdiction: str
    request_snapshot: dict[str, Any]
    result_snapshot: FormulationScreeningResponse
    created_at: datetime
    current_input_matches: bool | None = None


class SignedFileView(StrictModel):
    url: str
    expires_in: int


class PermanentDeleteRequest(StrictModel):
    confirmation: Literal["DELETE"]


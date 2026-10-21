from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from .agent import AgentSessionView
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


class ScreeningRunView(StrictModel):
    id: UUID
    formulation_version_id: UUID
    regulatory_dataset_id: str
    jurisdiction: str
    request_snapshot: dict[str, Any]
    result_snapshot: FormulationScreeningResponse
    created_at: datetime


class SignedFileView(StrictModel):
    url: str
    expires_in: int


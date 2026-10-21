from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .screening import StrictModel


ReviewStatus = Literal["not_reviewed", "in_review", "awaiting_information", "reviewed"]
FollowUpStatus = Literal["open", "resolved"]
ReviewTargetType = Literal["case", "formulation", "clarification", "review_item"]


class ReviewItemView(StrictModel):
    id: UUID
    screening_run_id: UUID
    subject_type: str
    subject_key: str
    submitted_row_number: int
    engine_finding: str
    requires_attention: bool
    review_status: ReviewStatus | None = None
    updated_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None


class ReviewStatusUpdate(StrictModel):
    review_status: ReviewStatus


class ReviewerNoteCreate(StrictModel):
    target_type: ReviewTargetType = "case"
    target_id: UUID | None = None
    body: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_target(self) -> "ReviewerNoteCreate":
        if self.target_type == "case" and self.target_id is not None:
            raise ValueError("Case notes do not accept a target_id")
        if self.target_type != "case" and self.target_id is None:
            raise ValueError("A target_id is required")
        return self


class ReviewerNoteView(StrictModel):
    id: UUID
    case_id: UUID
    formulation_version_id: UUID | None = None
    clarification_id: UUID | None = None
    review_item_id: UUID | None = None
    target_type: ReviewTargetType
    body: str
    created_by: UUID
    author_name: str
    created_at: datetime


class FollowUpCreate(StrictModel):
    target_type: ReviewTargetType = "case"
    target_id: UUID | None = None
    action_text: str = Field(min_length=1, max_length=1000)
    details: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_target(self) -> "FollowUpCreate":
        if self.target_type == "case" and self.target_id is not None:
            raise ValueError("Case follow-ups do not accept a target_id")
        if self.target_type != "case" and self.target_id is None:
            raise ValueError("A target_id is required")
        return self


class FollowUpUpdate(StrictModel):
    action_text: str | None = Field(default=None, min_length=1, max_length=1000)
    details: str | None = Field(default=None, max_length=4000)
    status: FollowUpStatus | None = None


class FollowUpView(StrictModel):
    id: UUID
    case_id: UUID
    formulation_version_id: UUID | None = None
    clarification_id: UUID | None = None
    review_item_id: UUID | None = None
    target_type: ReviewTargetType
    target_label: str | None = None
    action_text: str
    details: str | None = None
    status: FollowUpStatus
    created_by: UUID
    author_name: str
    resolved_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class ReviewWorkspaceView(StrictModel):
    case_id: UUID
    formulation_version_id: UUID
    screening_run_id: UUID | None = None
    clarification_targets: list["ClarificationReviewTarget"] = Field(default_factory=list)
    review_items: list[ReviewItemView] = Field(default_factory=list)
    notes: list[ReviewerNoteView] = Field(default_factory=list)
    follow_ups: list[FollowUpView] = Field(default_factory=list)


class ClarificationReviewTarget(StrictModel):
    id: UUID
    question_key: str
    row_id: str | None = None
    field_name: str
    question: str
    status: Literal["unresolved", "resolved", "dismissed"]


class ReviewOverviewView(StrictModel):
    case_id: UUID
    current_formulation_version_id: UUID | None = None
    latest_screening_run_id: UUID | None = None
    latest_screening_formulation_version_id: UUID | None = None
    latest_screening_at: datetime | None = None
    ingredients_screened: int = 0
    attention_findings: int = 0
    not_reviewed: int = 0
    in_review: int = 0
    awaiting_information: int = 0
    reviewed: int = 0
    open_follow_ups: int = 0
    unresolved_clarifications: int = 0
    note_count: int = 0
    last_review_activity_at: datetime | None = None
    recent_case_notes: list[ReviewerNoteView] = Field(default_factory=list)
    open_follow_up_items: list[FollowUpView] = Field(default_factory=list)


ActivityContextType = Literal["case", "formulation", "clarification", "finding"]


class ActivityContextView(StrictModel):
    case_id: UUID
    case_name: str
    target_type: ActivityContextType
    target_label: str
    formulation_version_id: UUID | None = None
    formulation_version_number: int | None = None
    screening_run_id: UUID | None = None
    screening_run_number: int | None = None
    screening_at: datetime | None = None
    regulatory_dataset_id: str | None = None
    clarification_id: UUID | None = None
    clarification_question_key: str | None = None
    clarification_question: str | None = None
    source_row_number: int | None = None
    review_item_id: UUID | None = None
    submitted_row_number: int | None = None
    ingredient_name: str | None = None
    engine_finding: str | None = None


class NoteActivityView(StrictModel):
    id: UUID
    kind: Literal["note"] = "note"
    occurred_at: datetime
    author_name: str
    context: ActivityContextView
    body: str


class FollowUpActivityView(StrictModel):
    id: UUID
    kind: Literal["follow_up"] = "follow_up"
    occurred_at: datetime
    author_name: str
    context: ActivityContextView
    action_text: str
    details: str | None = None
    status: FollowUpStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    resolved_by_name: str | None = None


class ReviewUpdateActivityView(StrictModel):
    id: UUID
    kind: Literal["review_update"] = "review_update"
    occurred_at: datetime
    author_name: str
    context: ActivityContextView
    review_status: ReviewStatus


class CaseActivityView(StrictModel):
    case_id: UUID
    entries: list[NoteActivityView | FollowUpActivityView | ReviewUpdateActivityView] = Field(default_factory=list)

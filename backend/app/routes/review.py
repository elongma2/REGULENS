from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.dependencies.auth import CurrentUser, get_current_user, get_supabase_gateway
from backend.app.models.review import (
    CaseActivityView,
    FollowUpCreate,
    FollowUpUpdate,
    FollowUpView,
    ReviewItemView,
    ReviewOverviewView,
    ReviewerNoteCreate,
    ReviewerNoteView,
    ReviewStatusUpdate,
    ReviewWorkspaceView,
)
from backend.app.services.supabase_gateway import ResourceNotFoundError, SupabaseGateway


router = APIRouter(tags=["professional-review"])


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "resource_not_found", "message": str(error).strip("'")})


@router.get("/cases/{case_id}/review-overview", response_model=ReviewOverviewView)
def case_review_overview(
    case_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> ReviewOverviewView:
    try:
        return ReviewOverviewView.model_validate(gateway.review_overview(user.id, case_id))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/cases/{case_id}/activity", response_model=CaseActivityView)
def case_activity(
    case_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> CaseActivityView:
    try:
        return CaseActivityView.model_validate(gateway.case_activity(user.id, case_id))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.get("/formulations/{version_id}/review-workspace", response_model=ReviewWorkspaceView)
def formulation_review_workspace(
    version_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
    screening_run_id: Annotated[UUID | None, Query()] = None,
) -> ReviewWorkspaceView:
    try:
        return ReviewWorkspaceView.model_validate(
            gateway.review_workspace(user.id, version_id, screening_run_id)
        )
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.patch("/review-items/{review_item_id}", response_model=ReviewItemView)
def update_review_item(
    review_item_id: UUID,
    payload: ReviewStatusUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> ReviewItemView:
    try:
        return ReviewItemView.model_validate(
            gateway.update_review_status(user.id, review_item_id, payload.review_status)
        )
    except ResourceNotFoundError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "review_status_invalid", "message": str(error)}) from error


@router.post("/cases/{case_id}/review-notes", response_model=ReviewerNoteView, status_code=201)
def create_reviewer_note(
    case_id: UUID,
    payload: ReviewerNoteCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> ReviewerNoteView:
    try:
        return ReviewerNoteView.model_validate(gateway.create_reviewer_note(
            user.id, case_id, payload.target_type, payload.target_id, payload.body,
        ))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.post("/cases/{case_id}/follow-ups", response_model=FollowUpView, status_code=201)
def create_follow_up(
    case_id: UUID,
    payload: FollowUpCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FollowUpView:
    try:
        return FollowUpView.model_validate(gateway.create_follow_up(
            user.id, case_id, payload.target_type, payload.target_id,
            payload.action_text, payload.details,
        ))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error


@router.patch("/follow-ups/{follow_up_id}", response_model=FollowUpView)
def update_follow_up(
    follow_up_id: UUID,
    payload: FollowUpUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> FollowUpView:
    try:
        changes = payload.model_dump(mode="json", exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail={"code": "follow_up_update_empty", "message": "Provide a follow-up change."})
        return FollowUpView.model_validate(gateway.update_follow_up(user.id, follow_up_id, changes))
    except ResourceNotFoundError as error:
        raise _not_found(error) from error

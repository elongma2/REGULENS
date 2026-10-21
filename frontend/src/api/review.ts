import { apiFetch } from "./http";
import { ApiError } from "./screening";
import type { CaseActivity, FollowUp, ReviewItem, ReviewOverview, ReviewerNote, ReviewStatus, ReviewTargetType, ReviewWorkspace } from "../types/review";

async function parse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload as T;
  const detail = payload?.detail;
  throw new ApiError(typeof detail === "object" ? detail?.message : detail || "The request failed.", response.status, typeof detail === "object" ? detail?.code : undefined);
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return parse<T>(await apiFetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  }));
}

export const getReviewOverview = (caseId: string) => json<ReviewOverview>(`/cases/${encodeURIComponent(caseId)}/review-overview`);
export const getCaseActivity = (caseId: string) => json<CaseActivity>(`/cases/${encodeURIComponent(caseId)}/activity`);

export function getReviewWorkspace(versionId: string, screeningRunId?: string | null) {
  const query = screeningRunId ? `?screening_run_id=${encodeURIComponent(screeningRunId)}` : "";
  return json<ReviewWorkspace>(`/formulations/${encodeURIComponent(versionId)}/review-workspace${query}`);
}

export function updateReviewStatus(reviewItemId: string, reviewStatus: ReviewStatus) {
  return json<ReviewItem>(`/review-items/${encodeURIComponent(reviewItemId)}`, {
    method: "PATCH",
    body: JSON.stringify({ review_status: reviewStatus }),
  });
}

export function addReviewerNote(caseId: string, targetType: ReviewTargetType, targetId: string | null, body: string) {
  return json<ReviewerNote>(`/cases/${encodeURIComponent(caseId)}/review-notes`, {
    method: "POST",
    body: JSON.stringify({ target_type: targetType, target_id: targetId, body }),
  });
}

export function addFollowUp(caseId: string, targetType: ReviewTargetType, targetId: string | null, actionText: string, details?: string | null) {
  return json<FollowUp>(`/cases/${encodeURIComponent(caseId)}/follow-ups`, {
    method: "POST",
    body: JSON.stringify({ target_type: targetType, target_id: targetId, action_text: actionText, details: details || null }),
  });
}

export function updateFollowUp(followUpId: string, changes: Partial<Pick<FollowUp, "action_text" | "details" | "status">>) {
  return json<FollowUp>(`/follow-ups/${encodeURIComponent(followUpId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

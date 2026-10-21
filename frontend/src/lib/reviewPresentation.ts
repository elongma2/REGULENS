import type { ReviewStatus } from "../types/review";

export type WritePhase = "idle" | "saving" | "saved" | "failed";

export interface WriteState {
  phase: WritePhase;
  message?: string;
}

export const idleWriteState: WriteState = { phase: "idle" };

export const reviewStatusPresentation: Record<ReviewStatus, { label: string; className: string }> = {
  not_reviewed: { label: "Not reviewed", className: "is-not-reviewed" },
  in_review: { label: "In review", className: "is-in-review" },
  awaiting_information: { label: "Awaiting information", className: "is-awaiting-information" },
  reviewed: { label: "Reviewed", className: "is-reviewed" },
};

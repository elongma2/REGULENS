import type { CaseReviewSummary, CaseView, FormulationVersionSummary, VersionStatus } from "../types/cases";
import type { ReviewOverview } from "../types/review";

export type CaseWorkflowFilter = "all" | "awaiting_formulation" | "input" | "ready" | "screened" | "failed";

export type CaseNextAction =
  | { kind: "upload"; label: "Upload formulation"; href: null }
  | { kind: "retry"; label: "Retry interpretation"; href: string; versionId: string }
  | { kind: "clarify"; label: "Continue clarification"; href: string; versionId: string }
  | { kind: "screen"; label: "Start screening"; href: string; versionId: string }
  | { kind: "review"; label: "Continue review"; href: string; versionId: string; runId: string | null }
  | { kind: "view"; label: "View screening"; href: string; versionId: string; runId: string | null };

const workflowLabels: Record<VersionStatus, string> = {
  uploaded: "Input uploaded",
  interpreting: "Interpreting input",
  clarification_required: "Input clarification needed",
  interpreted: "Input ready for review",
  ready_to_screen: "Ready to screen",
  screened: "Screened",
  failed: "Interpretation failed",
};

export function currentVersion(record: CaseView): FormulationVersionSummary | null {
  return record.latest_formulation ?? record.formulations[0] ?? null;
}

export function workflowLabel(record: CaseView): string {
  const version = currentVersion(record);
  return version ? workflowLabels[version.status] : "Awaiting formulation";
}

export function workflowFilter(record: CaseView): Exclude<CaseWorkflowFilter, "all"> {
  const version = currentVersion(record);
  if (!version) return "awaiting_formulation";
  if (version.status === "failed") return "failed";
  if (["interpreted", "ready_to_screen"].includes(version.status)) return "ready";
  if (version.status === "screened") return "screened";
  return "input";
}

export function reviewerItemsRemaining(progress: CaseReviewSummary | ReviewOverview | null | undefined): number | null {
  if (!progress) return null;
  if ("reviewer_items_remaining" in progress) return progress.reviewer_items_remaining;
  return progress.not_reviewed + progress.in_review + progress.awaiting_information;
}

export function resolveCaseAction(record: CaseView, progress: CaseReviewSummary | ReviewOverview | null | undefined): CaseNextAction {
  const version = currentVersion(record);
  if (!version) return { kind: "upload", label: "Upload formulation", href: null };
  const formulationHref = `/cases/${record.id}/formulations/${version.id}?tab=formulation`;
  if (version.status === "failed") return { kind: "retry", label: "Retry interpretation", href: formulationHref, versionId: version.id };
  if (["uploaded", "interpreting", "clarification_required"].includes(version.status)) {
    return { kind: "clarify", label: "Continue clarification", href: formulationHref, versionId: version.id };
  }
  if (["interpreted", "ready_to_screen"].includes(version.status) || version.screening_count === 0) {
    return { kind: "screen", label: "Start screening", href: formulationHref, versionId: version.id };
  }

  const screenedVersionId = progress?.latest_screening_formulation_version_id ?? version.id;
  const runId = progress?.latest_screening_run_id ?? null;
  const runQuery = runId ? `&run=${encodeURIComponent(runId)}` : "";
  const remaining = reviewerItemsRemaining(progress);
  if ((remaining ?? 0) > 0) {
    return {
      kind: "review", label: "Continue review", versionId: screenedVersionId, runId,
      href: `/cases/${record.id}/formulations/${screenedVersionId}?tab=results${runQuery}&resume=review&drawer=review`,
    };
  }
  if ((progress?.open_follow_ups ?? 0) > 0) {
    return {
      kind: "review", label: "Continue review", versionId: screenedVersionId, runId,
      href: `/cases/${record.id}/formulations/${screenedVersionId}?tab=activity${runQuery}&activity=open-followups`,
    };
  }
  return {
    kind: "view", label: "View screening", versionId: screenedVersionId, runId,
    href: `/cases/${record.id}/formulations/${screenedVersionId}?tab=results${runQuery}`,
  };
}

export function nextCaseAction(record: CaseView, progress: CaseReviewSummary | ReviewOverview | null | undefined): string {
  return resolveCaseAction(record, progress).label;
}

export function hasUnfinishedWork(record: CaseView): boolean {
  if (record.status !== "active") return false;
  return resolveCaseAction(record, record.review_summary).kind !== "view";
}

export function formatRelativeDate(value: string): string {
  const timestamp = new Date(value).getTime();
  const seconds = Math.round((timestamp - Date.now()) / 1000);
  const absolute = Math.abs(seconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absolute < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  const days = Math.round(hours / 24);
  if (Math.abs(days) < 7) return formatter.format(days, "day");
  return new Date(value).toLocaleDateString();
}

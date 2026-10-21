import type { AgentSession } from "./agent";
import type { FormulationRequest, ScreeningResponse } from "./screening";

export interface Organisation { id: string; name: string; role: "owner" | "member"; created_at: string; }
export interface CurrentUser { id: string; email: string | null; display_name: string; default_organisation_id: string; organisations: Organisation[]; }
export type VersionStatus = "uploaded" | "interpreting" | "clarification_required" | "interpreted" | "ready_to_screen" | "screened" | "failed";
export interface FormulationVersionSummary { id: string; case_id: string; version_number: number; original_filename: string | null; status: VersionStatus; revision: number; created_at: string; updated_at: string; screening_count: number; }
export interface CaseReviewSummary { latest_screening_run_id: string | null; latest_screening_formulation_version_id: string | null; latest_screening_at: string | null; attention_results: number; reviewer_items_remaining: number; open_follow_ups: number; unresolved_clarifications: number; last_review_activity_at: string | null; }
export interface CaseView { id: string; organisation_id: string; name: string; client_name: string | null; product_type: string | null; status: "active" | "archived"; created_at: string; updated_at: string; archived_at: string | null; formulations: FormulationVersionSummary[]; latest_formulation?: FormulationVersionSummary | null; latest_finding_count?: number | null; review_summary?: CaseReviewSummary | null; }
export interface FormulationVersion extends FormulationVersionSummary { raw_extraction: Record<string, unknown> | null; agent_session: AgentSession | null; canonical_formulation: FormulationRequest | null; product_context: Record<string, unknown> | null; }
export interface ScreeningRun { id: string; formulation_version_id: string; regulatory_dataset_id: string; jurisdiction: string; request_snapshot: FormulationRequest; result_snapshot: ScreeningResponse; created_at: string; }


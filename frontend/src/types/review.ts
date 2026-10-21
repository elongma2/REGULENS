export type ReviewStatus = "not_reviewed" | "in_review" | "awaiting_information" | "reviewed";
export type FollowUpStatus = "open" | "resolved";
export type ReviewTargetType = "case" | "formulation" | "clarification" | "review_item";
export type ReviewDataState = "loading" | "available" | "unavailable" | "not_applicable";

export interface ReviewItem {
  id: string;
  screening_run_id: string;
  subject_type: string;
  subject_key: string;
  submitted_row_number: number;
  engine_finding: string;
  requires_attention: boolean;
  review_status: ReviewStatus | null;
  updated_by: string | null;
  updated_at: string;
  reviewed_at: string | null;
}

export interface ReviewerNote {
  id: string;
  case_id: string;
  formulation_version_id: string | null;
  clarification_id: string | null;
  review_item_id: string | null;
  target_type: ReviewTargetType;
  body: string;
  created_by: string;
  author_name: string;
  created_at: string;
}

export interface FollowUp {
  id: string;
  case_id: string;
  formulation_version_id: string | null;
  clarification_id: string | null;
  review_item_id: string | null;
  target_type: ReviewTargetType;
  target_label: string | null;
  action_text: string;
  details: string | null;
  status: FollowUpStatus;
  created_by: string;
  author_name: string;
  resolved_by: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface ReviewWorkspace {
  case_id: string;
  formulation_version_id: string;
  screening_run_id: string | null;
  clarification_targets: Array<{ id: string; question_key: string; row_id: string | null; field_name: string; question: string; status: "unresolved" | "resolved" | "dismissed" }>;
  review_items: ReviewItem[];
  notes: ReviewerNote[];
  follow_ups: FollowUp[];
}

export interface ReviewOverview {
  case_id: string;
  current_formulation_version_id: string | null;
  latest_screening_run_id: string | null;
  latest_screening_formulation_version_id: string | null;
  latest_screening_at: string | null;
  ingredients_screened: number;
  attention_findings: number;
  not_reviewed: number;
  in_review: number;
  awaiting_information: number;
  reviewed: number;
  open_follow_ups: number;
  unresolved_clarifications: number;
  note_count: number;
  last_review_activity_at: string | null;
  recent_case_notes: ReviewerNote[];
  open_follow_up_items: FollowUp[];
}

export type ActivityContextType = "case" | "formulation" | "clarification" | "finding";

export interface ActivityContext {
  case_id: string;
  case_name: string;
  target_type: ActivityContextType;
  target_label: string;
  formulation_version_id: string | null;
  formulation_version_number: number | null;
  screening_run_id: string | null;
  screening_run_number: number | null;
  screening_at: string | null;
  regulatory_dataset_id: string | null;
  clarification_id: string | null;
  clarification_question_key: string | null;
  clarification_question: string | null;
  source_row_number: number | null;
  review_item_id: string | null;
  submitted_row_number: number | null;
  ingredient_name: string | null;
  engine_finding: string | null;
}

interface ActivityEntryBase {
  id: string;
  occurred_at: string;
  author_name: string;
  context: ActivityContext;
}

export interface NoteActivityEntry extends ActivityEntryBase {
  kind: "note";
  body: string;
}

export interface FollowUpActivityEntry extends ActivityEntryBase {
  kind: "follow_up";
  action_text: string;
  details: string | null;
  status: FollowUpStatus;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  resolved_by_name: string | null;
}

export interface ReviewUpdateActivityEntry extends ActivityEntryBase {
  kind: "review_update";
  review_status: ReviewStatus;
}

export type CaseActivityEntry = NoteActivityEntry | FollowUpActivityEntry | ReviewUpdateActivityEntry;
export interface CaseActivity { case_id: string; entries: CaseActivityEntry[]; }

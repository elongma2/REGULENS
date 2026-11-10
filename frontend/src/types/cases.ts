import type { AgentSession } from "./agent";
import type { FormulationRequest, RegulatedFunction, ScreeningResponse } from "./screening";

export interface Organisation { id: string; name: string; role: "owner" | "member"; created_at: string; }
export interface CurrentUser { id: string; email: string | null; display_name: string; default_organisation_id: string; organisations: Organisation[]; }
export type VersionStatus = "uploaded" | "interpreting" | "clarification_required" | "interpreted" | "ready_to_screen" | "screened" | "failed";
export interface FormulationVersionSummary { id: string; case_id: string; version_number: number; original_filename: string | null; status: VersionStatus; revision: number; created_at: string; updated_at: string; screening_count: number; }
export interface CaseReviewSummary { latest_screening_run_id: string | null; latest_screening_formulation_version_id: string | null; latest_screening_at: string | null; attention_results: number; reviewer_items_remaining: number; open_follow_ups: number; unresolved_clarifications: number; last_review_activity_at: string | null; }
export interface CaseView { id: string; organisation_id: string; name: string; client_name: string | null; product_type: string | null; status: "active" | "archived"; created_at: string; updated_at: string; archived_at: string | null; formulations: FormulationVersionSummary[]; latest_formulation?: FormulationVersionSummary | null; latest_finding_count?: number | null; review_summary?: CaseReviewSummary | null; }
export interface FormulationVersion extends FormulationVersionSummary { raw_extraction: Record<string, unknown> | null; agent_session: AgentSession | null; canonical_formulation: FormulationRequest | null; product_context: Record<string, unknown> | null; assembly_state?: Record<string, unknown> | null; assembly_revision?: number; calculation_snapshot?: Record<string, unknown> | null; }
export interface ScreeningRun { id: string; formulation_version_id: string; regulatory_dataset_id: string; jurisdiction: string; request_snapshot: FormulationRequest; result_snapshot: ScreeningResponse; created_at: string; current_input_matches: boolean | null; }

export type DocumentRole = "finished_product_formulation" | "ingredient_list" | "supplier_composition" | "sds_msds" | "technical_document" | "unknown";
export type DocumentProcessingStatus = "uploaded" | "parsing" | "classifying" | "extracting" | "needs_confirmation" | "ready" | "interrupted" | "failed";
export type SupplierDocumentLibraryStatus = "processing" | "available" | "needs_confirmation" | "archived" | "failed";

export interface DocumentRoleEvidence {
  role: DocumentRole;
  confidence: "confirmed" | "high" | "medium" | "low";
  page: number | null;
  source_snippet: string | null;
  reasons: string[];
}

export interface SupplierDocument {
  id: string;
  organisation_id: string;
  original_filename: string;
  mime_type: string;
  sha256: string;
  page_count: number | null;
  supplier_name: string | null;
  trade_name: string | null;
  product_code: string | null;
  document_revision_label: string | null;
  document_date: string | null;
  supersedes_supplier_document_id: string | null;
  detected_roles: DocumentRoleEvidence[];
  confirmed_roles: DocumentRole[];
  extraction_schema_version: string | null;
  processing_status: DocumentProcessingStatus;
  library_status: SupplierDocumentLibraryStatus;
  processing_diagnostics: Record<string, unknown> | null;
  error: { code?: string; message?: string; recoverable?: boolean; next_action?: string } | null;
  processing_key: string | null;
  processing_attempt: number;
  revision: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SupplierDocumentDetail extends SupplierDocument {
  parsed_content: Record<string, unknown> | null;
  extraction_result: Record<string, unknown> | null;
  model_configuration: string | null;
}

export interface FormulationDocument {
  id: string;
  formulation_version_id: string;
  supplier_document_id: string | null;
  original_filename: string;
  mime_type: string;
  sha256: string;
  page_count: number | null;
  processing_status: DocumentProcessingStatus;
  detected_roles: DocumentRoleEvidence[];
  confirmed_roles: DocumentRole[];
  parsed_content: Record<string, unknown> | null;
  extraction_result: Record<string, unknown> | null;
  processing_diagnostics: Record<string, unknown> | null;
  error: { code?: string; message?: string; recoverable?: boolean; next_action?: string } | null;
  document_revision_label: string | null;
  governing_for_material: boolean;
  extraction_schema_version?: string | null;
  extraction_current?: boolean;
  attached_extraction_key: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface FormulationDocumentBatch {
  documents: FormulationDocument[];
  failures: Array<{
    filename: string;
    code: string;
    message: string;
    recoverable: boolean;
  }>;
}

export interface SupplierDocumentBatch {
  documents: SupplierDocument[];
  failures: FormulationDocumentBatch["failures"];
}

export type CompositionQuantityKind = "exact" | "range" | "upper_bound" | "lower_bound" | "approximate" | "coded_range" | "remainder_to_total" | "unknown";
export interface CompositionQuantity {
  kind: CompositionQuantityKind;
  value: number | null;
  lower: number | null;
  upper: number | null;
  lower_inclusive: boolean | null;
  upper_inclusive: boolean | null;
  unit: string | null;
  basis: string | null;
  preparation_stage: string | null;
  quantity_scope: "supplier_material" | "finished_product" | null;
  raw_text: string | null;
  reported_code: string | null;
  legend_entry_id: string | null;
  approximate: boolean;
}

export interface MaterialConstituent {
  constituent_id: string;
  submitted_name: string;
  cas_number: string | null;
  composition_quantity: CompositionQuantity | null;
  source_evidence: Array<{
    document_id: string;
    page: number | null;
    source_row: number | null;
    source_column: string | null;
    source_snippet: string | null;
    raw_value: string | null;
  }>;
  verified_identity_group: string | null;
  regulated_functions: RegulatedFunction[];
  role_label: string | null;
  user_edits: Record<string, unknown>;
}

export interface SupplierMaterialState {
  material_id: string;
  trade_name: string;
  supplier_name: string | null;
  product_code: string | null;
  finished_product_usage: CompositionQuantity | null;
  attached_document_ids: string[];
  governing_document_id: string | null;
  conflicting_document_ids: string[];
  constituents: MaterialConstituent[];
  removed_constituent_ids?: string[];
  disclosure_status: "complete" | "partial" | "unknown";
  confirmation_status: "proposed" | "confirmed" | "needs_confirmation";
}

export interface FormulationAssemblyState {
  direct_ingredients: unknown[];
  materials: SupplierMaterialState[];
  formulation_row_ownership: Array<{
    row_id: string;
    owner_type: "direct_ingredient" | "supplier_material";
    material_id: string | null;
    candidate_material_ids: string[];
  }>;
  source_document_ids: string[];
  source_document_snapshots: Record<string, string>;
  source_document_metadata?: Record<string, {
    original_filename: string | null;
    supplier_name: string | null;
    trade_name: string | null;
    product_code: string | null;
  }>;
  formulation_name: string | null;
  product_context: string | null;
  product_applicability: Record<string, boolean | null>;
}

export interface AssemblyIssue {
  issue_id: string;
  code: string;
  severity: "error" | "review_required" | "warning";
  message: string;
  reviewer_action: string;
  blocking_for_calculation: boolean;
  blocking_for_full_evaluation: boolean;
  document_ids: string[];
  material_ids: string[];
  constituent_ids: string[];
}

export interface AssemblyPreparation {
  assembly_revision: number;
  state: FormulationAssemblyState;
  assembly: {
    assembly_revision: number;
    completeness: "complete" | "partial" | "blocked";
    issues: AssemblyIssue[];
    included_ingredients: Array<{
      verified_identity_group: string;
      display_name: string;
      cas_number: string | null;
      aggregate_quantity: CompositionQuantity;
      contributions: unknown[];
      completeness: "complete" | "partial" | "blocked";
    }>;
    unresolved_raw_materials: string[];
    incomplete_disclosures: string[];
    unresolved_associations: string[];
    excluded_items: Array<Record<string, unknown>>;
    evaluated_scope: Record<string, unknown>;
    calculation_snapshot: Record<string, unknown>;
  };
  formulation: FormulationRequest | null;
}


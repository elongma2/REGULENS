import type { CatalogueIdentity, ConcentrationBasis, ConcentrationUnit, FormulationRequest, OpenAIUsage, PreparationStage, ProductApplicabilityFacts, RegulatedFunction } from "./screening";

export type AgentSessionState = "uploaded" | "parsing" | "interpreted" | "needs_confirmation" | "ready" | "failed";
export type AgentConfidence = "confirmed" | "high_confidence" | "needs_confirmation" | "unresolved";

export interface AgentFieldProvenance<T = unknown> {
  value: T;
  source_value: string | null;
  source_row: number;
  source_column: string | null;
  interpretation_method: string;
  needs_confirmation: boolean;
  confirmed_by_user: boolean;
  source_references: AgentSourceReference[];
}

export interface AgentSourceReference {
  source_row: number;
  source_column_index: number;
  source_column: string | null;
  source_value: string;
}

export interface AgentConcentration {
  value: AgentFieldProvenance<number> | null;
  unit: AgentFieldProvenance<ConcentrationUnit | null> | null;
  basis: AgentFieldProvenance<ConcentrationBasis | null>;
  preparation_stage: AgentFieldProvenance<PreparationStage | null> | null;
}

export interface AgentSourceMetadata {
  source_row: number | null;
  source_column: string;
  source_column_index: number;
  source_value: string;
  mapped_as: string;
}

export interface AgentIngredientRow {
  row_id: string;
  source_row: number;
  source_rows: number[];
  source_cells: string[];
  name: AgentFieldProvenance<string>;
  cas_number: AgentFieldProvenance<string | null> | null;
  concentration: AgentConcentration | null;
  identity_status: AgentConfidence;
  identity_catalogue_id: string | null;
  catalogue_identity: CatalogueIdentity | null;
  source_metadata: AgentSourceMetadata[];
  issues: string[];
  unresolved_fields: AgentRowUncertainty[];
  regulated_functions?: RegulatedFunction[];
  function_sources?: AgentSourceReference[];
}

export interface AgentRowUncertainty {
  target_field: "ingredient_name" | "concentration" | "concentration.unit" | "preparation_stage" | "regulated_functions";
  uncertainty_code: "ingredient_identity" | "missing_concentration_unit" | "concentration_unavailable" | "preparation_stage" | "ingredient_function";
  source_value: string | null;
  proposed_value: unknown;
}

export interface AgentQuestionOption { option_id: string; label: string; value: unknown; }
export interface AgentQuestion {
  question_id: string;
  question_type: "identity" | "unit" | "preparation_stage" | "product_context" | "non_numeric_concentration" | "mapping" | "ingredient_function";
  title: string;
  prompt: string;
  source_row: number | null;
  row_id: string | null;
  target_field: "ingredient_name" | "concentration" | "concentration.unit" | "preparation_stage" | "product_context" | "column_mapping" | "regulated_functions" | null;
  uncertainty_code: "ingredient_identity" | "missing_concentration_unit" | "concentration_unavailable" | "preparation_stage" | "product_context" | "column_mapping" | "ingredient_function" | null;
  affected_row_ids: string[];
  blocking: boolean;
  options: AgentQuestionOption[];
}

export interface AgentAttemptDiagnostic {
  attempt_number: number;
  status: "success" | "failure";
  failure_category: string | null;
  configured_model: string;
  actual_model: string | null;
  response_ids: string[];
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  tool_calls: number;
  request_rounds: number;
}

export interface AgentSession {
  session_id: string;
  revision: number;
  state: AgentSessionState;
  filename: string;
  detected_table: { header_row: number; data_start_row: number; header_rows: number[]; data_rows: number[]; source_row_count: number; source_column_count: number; delimiter: string } | null;
  column_mappings: Array<{ source_column: string; source_column_index: number; mapped_field: string; confidence: AgentConfidence }>;
  formulation_id: AgentFieldProvenance<string | null> | null;
  formulation_name: AgentFieldProvenance<string | null> | null;
  product_context: AgentFieldProvenance<string | null> | null;
  product_applicability?: ProductApplicabilityFacts;
  interpreted_rows: AgentIngredientRow[];
  questions: AgentQuestion[];
  activity: Array<{ activity_id: string; status: "complete" | "warning" | "error"; message: string }>;
  canonical_formulation: FormulationRequest | null;
  error: { code: string; message: string; recoverable: boolean } | null;
  model: string | null;
  usage: OpenAIUsage | null;
  attempts: number;
  successful_attempt: number | null;
  attempt_diagnostics: AgentAttemptDiagnostic[];
  total_usage: OpenAIUsage | null;
}

export interface AgentPreparedFormulation {
  session: AgentSession;
  formulation: FormulationRequest;
  row_provenance: AgentIngredientRow[];
}

export interface AgentRowUpdate {
  row_id?: string;
  source_row?: number;
  name?: string;
  cas_number?: string | null;
  concentration_value?: number | null;
  concentration_unit?: ConcentrationUnit | null;
  concentration_basis?: ConcentrationBasis | null;
  preparation_stage?: PreparationStage | null;
  remove_concentration?: boolean;
  regulated_functions?: RegulatedFunction[];
}

export interface InputProvenance {
  filename: string;
  sourceRow: number;
  sourceRows: number[];
  originalValue: string | null;
  interpretedValue: string;
  method: string;
  confirmedByUser: boolean;
  sourceMetadata: AgentSourceMetadata[];
}

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .formulation import FormulationRequest, ProductApplicabilityFacts
from .openai import OpenAIUsage
from .screening import CatalogueIdentity, RegulatedFunction, StrictModel


class AgentSessionState(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    INTERPRETED = "interpreted"
    NEEDS_CONFIRMATION = "needs_confirmation"
    READY = "ready"
    FAILED = "failed"


class AgentConfidence(StrEnum):
    CONFIRMED = "confirmed"
    HIGH_CONFIDENCE = "high_confidence"
    NEEDS_CONFIRMATION = "needs_confirmation"
    UNRESOLVED = "unresolved"


class AgentFieldProvenance(StrictModel):
    value: Any = None
    source_value: str | None = None
    source_row: int
    source_column: str | None = None
    interpretation_method: str
    needs_confirmation: bool = False
    confirmed_by_user: bool = False
    source_references: list["AgentSourceReference"] = Field(default_factory=list)


class AgentSourceReference(StrictModel):
    source_row: int
    source_column_index: int
    source_column: str | None = None
    source_value: str


class AgentConcentration(StrictModel):
    value: AgentFieldProvenance | None = None
    unit: AgentFieldProvenance | None = None
    basis: AgentFieldProvenance
    preparation_stage: AgentFieldProvenance | None = None


class AgentSourceMetadata(StrictModel):
    source_row: int | None = None
    source_column: str
    source_column_index: int
    source_value: str
    mapped_as: str


class AgentRowUncertainty(StrictModel):
    target_field: Literal["ingredient_name", "cas_number", "concentration", "concentration.unit", "preparation_stage", "regulated_functions"]
    uncertainty_code: Literal[
        "ingredient_identity", "cas_number", "missing_concentration_unit", "concentration_unavailable", "preparation_stage", "ingredient_function",
    ]
    source_value: str | None = None
    proposed_value: Any = None


class AgentIngredientRow(StrictModel):
    row_id: str
    source_row: int
    source_rows: list[int] = Field(default_factory=list)
    source_cells: list[str]
    name: AgentFieldProvenance
    cas_number: AgentFieldProvenance | None = None
    concentration: AgentConcentration | None = None
    identity_status: AgentConfidence
    identity_catalogue_id: str | None = None
    catalogue_identity: CatalogueIdentity | None = None
    source_metadata: list[AgentSourceMetadata] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    unresolved_fields: list[AgentRowUncertainty] = Field(default_factory=list)
    regulated_functions: list[RegulatedFunction] = Field(default_factory=list)
    function_sources: list[AgentSourceReference] = Field(default_factory=list)


class AgentColumnMapping(StrictModel):
    source_column: str
    source_column_index: int
    mapped_field: Literal[
        "ingredient_name", "cas_number", "concentration", "unit", "basis",
        "preparation_stage", "product_context", "formulation_id", "formulation_name",
        "raw_material_name", "notes", "metadata", "ignore",
        "ingredient_function",
    ]
    confidence: AgentConfidence


class AgentDetectedTable(StrictModel):
    header_row: int
    data_start_row: int
    header_rows: list[int] = Field(default_factory=list)
    data_rows: list[int] = Field(default_factory=list)
    source_row_count: int
    source_column_count: int
    delimiter: str


class AgentQuestionOption(StrictModel):
    option_id: str
    label: str
    value: Any = None


class AgentQuestion(StrictModel):
    question_id: str
    question_type: Literal["identity", "cas_number", "unit", "preparation_stage", "product_context", "non_numeric_concentration", "mapping", "ingredient_function"]
    title: str
    prompt: str
    source_row: int | None = None
    row_id: str | None = None
    target_field: Literal[
        "ingredient_name", "cas_number", "concentration", "concentration.unit", "preparation_stage", "product_context", "column_mapping", "regulated_functions",
    ] | None = None
    uncertainty_code: Literal[
        "ingredient_identity", "cas_number", "missing_concentration_unit", "concentration_unavailable", "preparation_stage",
        "product_context", "column_mapping", "ingredient_function",
    ] | None = None
    affected_row_ids: list[str] = Field(default_factory=list)
    blocking: bool = True
    options: list[AgentQuestionOption] = Field(default_factory=list)


class AgentActivityItem(StrictModel):
    activity_id: str
    status: Literal["complete", "warning", "error"]
    message: str


class AgentFailure(StrictModel):
    code: str
    message: str
    recoverable: bool = True


class AgentAttemptDiagnostic(StrictModel):
    attempt_number: int = Field(ge=1)
    status: Literal["success", "failure"]
    failure_category: str | None = None
    configured_model: str
    actual_model: str | None = None
    response_ids: list[str] = Field(default_factory=list)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    request_rounds: int = Field(default=0, ge=0)


class AgentSessionView(StrictModel):
    session_id: str
    revision: int
    state: AgentSessionState
    filename: str
    detected_table: AgentDetectedTable | None = None
    column_mappings: list[AgentColumnMapping] = Field(default_factory=list)
    formulation_id: AgentFieldProvenance | None = None
    formulation_name: AgentFieldProvenance | None = None
    product_context: AgentFieldProvenance | None = None
    product_applicability: ProductApplicabilityFacts = Field(default_factory=ProductApplicabilityFacts)
    interpreted_rows: list[AgentIngredientRow] = Field(default_factory=list)
    questions: list[AgentQuestion] = Field(default_factory=list)
    activity: list[AgentActivityItem] = Field(default_factory=list)
    canonical_formulation: FormulationRequest | None = None
    error: AgentFailure | None = None
    model: str | None = None
    usage: OpenAIUsage | None = None
    attempts: int = Field(default=0, ge=0)
    successful_attempt: int | None = Field(default=None, ge=1)
    attempt_diagnostics: list[AgentAttemptDiagnostic] = Field(default_factory=list)
    total_usage: OpenAIUsage | None = None


class AgentAnswer(StrictModel):
    question_id: str
    option_id: str
    value: Any = None


class AgentRowUpdate(StrictModel):
    row_id: str | None = None
    source_row: int | None = None
    name: str | None = None
    cas_number: str | None = None
    concentration_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    concentration_unit: Literal["percent", "mg/kg", "ppm"] | None = None
    concentration_basis: Literal["NH3", "free base", "zinc", "sulphate", "hydrochloride", "tetrahydrochloride"] | None = None
    preparation_stage: Literal["finished_product", "after_mixing", "ready_for_use"] | None = None
    remove_concentration: bool = False
    regulated_functions: list[RegulatedFunction] | None = None

    @model_validator(mode="after")
    def require_row_selector(self) -> "AgentRowUpdate":
        if self.row_id is None and self.source_row is None:
            raise ValueError("A row_id or source_row is required")
        return self


class AgentAnswersRequest(StrictModel):
    revision: int
    answers: list[AgentAnswer] = Field(default_factory=list)
    row_updates: list[AgentRowUpdate] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_change(self) -> "AgentAnswersRequest":
        if not self.answers and not self.row_updates:
            raise ValueError("At least one answer or row update is required")
        return self


class AgentPrepareRequest(StrictModel):
    revision: int
    formulation_id: str | None = None
    formulation_name: str | None = None
    product_context: str | None = None
    product_applicability: ProductApplicabilityFacts = Field(default_factory=ProductApplicabilityFacts)

    @field_validator("formulation_id", "formulation_name", "product_context")
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Optional text fields must be null or non-blank")
        return value


class AgentPreparedFormulation(StrictModel):
    session: AgentSessionView
    formulation: FormulationRequest
    row_provenance: list[AgentIngredientRow]


class ModelSourceReference(StrictModel):
    source_row: int
    source_column_index: int
    source_value: str


class ModelColumnMapping(StrictModel):
    source_column_index: int
    mapped_field: Literal[
        "ingredient_name", "cas_number", "concentration", "unit", "basis",
        "preparation_stage", "product_context", "formulation_id", "formulation_name",
        "raw_material_name", "notes", "metadata", "ignore",
        "ingredient_function",
    ]
    confidence: AgentConfidence


class ModelIngredientInterpretation(StrictModel):
    row_id: str
    source_rows: list[int] = Field(min_length=1)
    interpreted_name: str
    identity_status: Literal["exact_match", "candidate", "unresolved"]
    name_sources: list[ModelSourceReference] = Field(min_length=1)
    proposed_cas: str | None
    cas_sources: list[ModelSourceReference]
    concentration_value: float | None
    concentration_unit: Literal["percent", "mg/kg", "ppm"] | None
    concentration_value_sources: list[ModelSourceReference]
    concentration_unit_sources: list[ModelSourceReference]
    basis: Literal["NH3", "free base", "zinc", "sulphate", "hydrochloride", "tetrahydrochloride"] | None
    basis_sources: list[ModelSourceReference]
    preparation_stage: Literal["finished_product", "after_mixing", "ready_for_use"] | None
    preparation_stage_sources: list[ModelSourceReference]
    # OpenAI strict structured outputs require every property to appear in the
    # schema's `required` array. The model must return empty lists when the CSV
    # supplies no regulated function.
    regulated_functions: list[RegulatedFunction]
    regulated_function_sources: list[ModelSourceReference]
    uncertainties: list[Literal[
        "ingredient_identity", "cas_number", "concentration_value", "concentration_unit",
        "concentration_basis", "preparation_stage",
        "ingredient_function",
    ]]
    issues: list[str]


class ModelMetadataValue(StrictModel):
    value: str | None
    sources: list[ModelSourceReference]


class ModelFormulationMetadata(StrictModel):
    formulation_id: ModelMetadataValue
    formulation_name: ModelMetadataValue
    product_context: ModelMetadataValue


class ModelInterpretation(StrictModel):
    header_rows: list[int] = Field(min_length=1)
    data_rows: list[int] = Field(min_length=1)
    column_mappings: list[ModelColumnMapping]
    ingredients: list[ModelIngredientInterpretation]
    formulation_metadata: ModelFormulationMetadata


class AgentModelRun(StrictModel):
    interpretation: ModelInterpretation
    usage: OpenAIUsage

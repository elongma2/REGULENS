from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Finding(StrEnum):
    NO_ISSUE = "no_issue_identified_within_scoped_rules"
    WITHIN_LIMIT = "restriction_within_limit"
    RESTRICTION_EXCEEDED = "restriction_exceeded"
    PROHIBITED = "prohibited_substance_identified"
    INFORMATION_MISSING = "information_missing"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    PROFESSIONAL_REVIEW = "professional_review_required"
    PERMITTED_USE_WITHIN_CONDITIONS = "permitted_use_within_conditions"
    PERMITTED_USE_CONDITION_NOT_MET = "permitted_use_condition_not_met"
    REGULATED_FUNCTION_NOT_PERMITTED = "regulated_function_not_permitted"


class RegulatedFunction(StrEnum):
    COLOURANT = "colourant"
    PRESERVATIVE = "preservative"
    UV_FILTER = "uv_filter"


class ConditionStatus(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    INFORMATION_MISSING = "information_missing"
    PROFESSIONAL_REVIEW = "professional_review"
    NOT_APPLICABLE = "not_applicable"


class WarningApplicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNDETERMINED = "undetermined"


class IdentityStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    REVIEW_REQUIRED = "review_required"


class ReviewType(StrEnum):
    IDENTITY = "identity_review"
    RULE = "rule_review"


class IdentitySourceType(StrEnum):
    SINGAPORE_REGULATORY = "singapore_regulatory_source"
    ACD_REGULATORY = "acd_regulatory_source"
    INGREDIENT_CATALOGUE = "ingredient_identity_catalogue"


class SingaporeLinkageStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    LINKED = "linked"
    VERIFIED_NOT_REPRESENTED = "verified_not_represented"
    UNRESOLVED = "unresolved"


class ConcentrationInput(StrictModel):
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: str = Field(min_length=1)
    basis: str | None
    preparation_stage: str = Field(min_length=1)

    @field_validator("unit", "preparation_stage")
    @classmethod
    def require_nonblank_semantics(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Concentration unit and preparation stage cannot be blank")
        return value

    @field_validator("basis")
    @classmethod
    def reject_blank_basis(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Concentration basis must be null or non-blank")
        return value


class IngredientInput(StrictModel):
    name: str | None = None
    cas_number: str | None = None
    concentration: ConcentrationInput | None = None
    regulated_functions: list[RegulatedFunction] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_identity_input(self) -> "IngredientInput":
        if not (self.name and self.name.strip()) and not (self.cas_number and self.cas_number.strip()):
            raise ValueError("At least one of ingredient name or CAS number is required")
        return self


class IdentityCandidate(StrictModel):
    substance_id: str
    source_document: str
    regulatory_section: str
    reference_number: str
    original_substance_name: str
    normalized_substance_name: str
    cas_numbers: list[str] = Field(default_factory=list)
    match_methods: list[str] = Field(default_factory=list)
    cross_reference_statuses: list[str] = Field(default_factory=list)


class CatalogueIdentity(StrictModel):
    ingredient_id: str
    canonical_name: str
    source_name: str
    source_document: str
    source_version: str
    source_url: str
    source_entries: list[int]
    source_pages: list[int]
    raw_record_ids: list[str]
    identity_dataset_version: str
    accepted_baseline_sha256: str


class LinkageTarget(StrictModel):
    raw_record_id: str
    rule_id: str
    substance_id: str
    part: str
    reference: str
    source_substance_name: str
    source_document: str
    source_hash: str


class LinkageReview(StrictModel):
    reviewed: bool
    reviewed_at: str
    reviewer: str
    review_basis: str
    notes: str


class LinkageEvidence(StrictModel):
    linkage_id: str
    accepted_status: SingaporeLinkageStatus
    applicable_to_active_baseline: bool
    identity_dataset_version: str
    identity_dataset_hash: str
    singapore_regulatory_baseline: str
    singapore_regulatory_baseline_hash: str
    screened_scope: list[str]
    singapore_targets: list[LinkageTarget] = Field(default_factory=list)
    review: LinkageReview
    inapplicability_reasons: list[str] = Field(default_factory=list)


class IdentityResolution(StrictModel):
    status: IdentityStatus
    match_methods: list[str] = Field(default_factory=list)
    singapore_candidates: list[IdentityCandidate] = Field(default_factory=list)
    acd_candidates: list[IdentityCandidate] = Field(default_factory=list)
    resolved_singapore_substance_id: str | None = None
    resolved_singapore_substance_ids: list[str] = Field(default_factory=list)
    identity_source_type: IdentitySourceType | None = None
    identity_source_name: str | None = None
    singapore_linkage_status: SingaporeLinkageStatus = SingaporeLinkageStatus.NOT_APPLICABLE
    catalogue_identity: CatalogueIdentity | None = None
    linkage_evidence: LinkageEvidence | None = None
    reasons: list[str] = Field(default_factory=list)


class RuleEvidence(StrictModel):
    dataset_version: str
    rule_id: str
    source_document: str
    source_version: str | None
    effective_date: str | None
    document_revision: str | None
    retrieval_date: str
    source_url: str
    regulatory_section: str
    reference_number: str
    substance_name: str
    product_context: str | None
    concentration: dict[str, Any] | None
    other_conditions: str | None
    required_warning: str | None
    source_text: str
    source_pages: list[int]
    normalization_status: str
    review_reasons: list[str]
    raw_record_id: str
    raw_fragments: list[dict[str, Any]] = Field(default_factory=list)
    regulation_6_provisions: list[dict[str, Any]] = Field(default_factory=list)
    cross_references: list[dict[str, Any]] = Field(default_factory=list)
    acd_counterpart_rules: list[dict[str, Any]] = Field(default_factory=list)
    regulatory_category: str | None = None
    list_semantics: str | None = None
    permitted_function: RegulatedFunction | None = None
    applicability_requirements: list[dict[str, Any]] = Field(default_factory=list)
    combined_limit_requirements: list[dict[str, Any]] = Field(default_factory=list)
    warning_requirements: list[dict[str, Any]] = Field(default_factory=list)
    source_bundle_version: str | None = None
    source_section_version: str | None = None


class RuleEvaluation(StrictModel):
    rule_id: str
    evaluation_status: str
    finding: Finding | None = None
    reasons: list[str] = Field(default_factory=list)
    submitted_concentration: ConcentrationInput | None = None
    evidence: RuleEvidence


class ConditionEvaluation(StrictModel):
    rule_id: str
    condition_type: str
    status: ConditionStatus
    source_text: str
    reason: str | None = None


class FunctionEvaluation(StrictModel):
    regulated_function: RegulatedFunction
    singapore_part: str
    status: ConditionStatus
    finding: Finding | None = None
    rule_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class WarningRequirement(StrictModel):
    rule_id: str
    warning_text: str
    trigger_text: str | None = None
    applicability: WarningApplicability
    source_reference: str


class ReviewExplanation(StrictModel):
    title: str = Field(max_length=80)
    summary: str = Field(max_length=500)
    what_to_check: str | None = Field(default=None, max_length=300)
    submitted_fact: str | None = Field(default=None, max_length=200)
    regulatory_fact: str | None = Field(default=None, max_length=300)
    source: Literal["model", "deterministic_fallback"]


class ScreeningResult(StrictModel):
    dataset_version: str
    accepted_baseline_sha256: str
    submitted_ingredient: IngredientInput
    submitted_product_context: str | None
    identity: IdentityResolution
    primary_finding: Finding
    confirmed_findings: list[Finding] = Field(default_factory=list)
    review_required: bool
    review_types: list[ReviewType] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    review_explanation: ReviewExplanation | None = None
    rule_evaluations: list[RuleEvaluation] = Field(default_factory=list)
    inactive_evidence: list[RuleEvidence] = Field(default_factory=list)
    searched_singapore_parts: list[str] = Field(default_factory=list)
    searched_regulatory_sections: list[str] = Field(default_factory=list)
    function_evaluations: list[FunctionEvaluation] = Field(default_factory=list)
    condition_evaluations: list[ConditionEvaluation] = Field(default_factory=list)
    warning_requirements: list[WarningRequirement] = Field(default_factory=list)
    incomplete_positive_list_checks: list[RegulatedFunction] = Field(default_factory=list)
    scope_note: str = (
        "This is an initial Singapore screening result within the implemented rules only; "
        "professional review remains required."
    )

    @model_validator(mode="after")
    def require_review_details(self) -> "ScreeningResult":
        if self.review_required and (not self.review_types or not self.review_reasons):
            raise ValueError("Review-required results must include review types and reasons")
        if not self.review_required and self.review_types:
            raise ValueError("Review types require review_required=true")
        self.review_types = list(dict.fromkeys(self.review_types))
        self.review_reasons = list(dict.fromkeys(self.review_reasons))
        return self

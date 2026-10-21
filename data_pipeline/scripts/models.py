from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDocument(StrictModel):
    source_document: str
    title: str
    authority: str
    filename: str
    sha256: str
    page_count: int
    source_url: str
    document_revision: str | None
    effective_date: str | None
    retrieval_date: str
    snapshot_generated_at: str | None = None
    pdf_metadata: dict[str, Any] = Field(default_factory=dict)


class RawFragment(StrictModel):
    source_page: int
    table_bbox: list[float] | None
    row_bbox: list[float] | None
    cells: list[str]
    original_row_text: str
    is_continuation: bool = False


class RawRecord(StrictModel):
    raw_record_id: str
    source_document: str
    section: str
    reference_number: str
    reference_number_raw: str
    original_substance_name: str
    cas_number_raw: str | None = None
    original_field_of_use_text: str | None = None
    original_concentration_text: str | None = None
    original_conditions_text: str | None = None
    original_warning_text: str | None = None
    source_text: str
    source_pages: list[int]
    fragments: list[RawFragment]
    footnote_references: list[str] = Field(default_factory=list)
    jurisdiction_notes: list[str] = Field(default_factory=list)
    extraction_flags: list[str] = Field(default_factory=list)


class ConcentrationConstraint(StrictModel):
    value: float
    unit: str
    comparator: Literal["less_than_or_equal", "less_than", "greater_than", "greater_than_or_equal"]
    basis: str | None = None
    preparation_stage: Literal["finished_product", "ready_for_use", "after_mixing", "ingredient", "unspecified"]
    source_field: Literal["maximum_concentration", "other_conditions", "substance_text"]
    source_text: str


class ApplicabilityRequirement(StrictModel):
    fact: Literal[
        "rinse_off",
        "leave_on",
        "oral_care",
        "eye_area",
        "mucous_membrane_contact",
        "brief_skin_contact",
        "spray_or_aerosol",
        "powder_form",
        "adult_use",
        "child_use",
        "sun_protection_purpose",
        "product_protection_purpose",
        "solely_hair_colouring",
    ]
    expected: bool
    source_text: str


class CombinedLimitRequirement(StrictModel):
    group_key: str
    maximum: ConcentrationConstraint
    constituent_references: list[str] = Field(default_factory=list)
    source_text: str


class WarningRequirement(StrictModel):
    warning_text: str
    trigger_text: str | None = None
    applicability: Literal["structured", "professional_review"] = "professional_review"


class NormalizedRule(StrictModel):
    rule_id: str
    parent_rule_id: str | None = None
    case_label: str | None = None
    source_document: str
    source_version: str | None
    source_bundle_version: str | None = None
    source_section_version: str | None = None
    source_hash: str
    effective_date: str | None
    source_snapshot_generated_at: str | None
    regulatory_section: str
    reference_number: str
    substance_id: str | None
    substance_name: str
    cas_numbers: list[str] = Field(default_factory=list)
    restriction_type: Literal["prohibited", "restricted", "permitted"]
    regulatory_category: Literal[
        "prohibited", "restricted", "colourant", "preservative", "uv_filter"
    ] = "restricted"
    list_semantics: Literal["prohibited", "restricted", "positive_list"] = "restricted"
    permitted_function: Literal["colourant", "preservative", "uv_filter"] | None = None
    regulatory_identifiers: dict[str, list[str]] = Field(default_factory=dict)
    product_context: str | None = None
    concentration: ConcentrationConstraint | None = None
    concentration_text: str | None = None
    other_conditions: str | None = None
    required_warning: str | None = None
    applicability_requirements: list[ApplicabilityRequirement] = Field(default_factory=list)
    combined_limit_requirements: list[CombinedLimitRequirement] = Field(default_factory=list)
    warning_requirements: list[WarningRequirement] = Field(default_factory=list)
    footnotes: list[dict[str, Any]] = Field(default_factory=list)
    supporting_source_texts: list[dict[str, Any]] = Field(default_factory=list)
    jurisdiction_notes: list[str] = Field(default_factory=list)
    source_text: str
    source_pages: list[int]
    source_url: str
    document_revision: str | None
    retrieval_date: str
    raw_record_id: str
    raw_file: str
    active: bool = True
    normalization_status: Literal[
        "normalized", "manual_review_required", "inactive_source_entry"
    ]
    review_reasons: list[str] = Field(default_factory=list)


class CrossReference(StrictModel):
    cross_reference_id: str
    regulatory_mapping: str
    reference_number: str
    acd_rule_ids: list[str] = Field(default_factory=list)
    singapore_rule_ids: list[str] = Field(default_factory=list)
    match_basis: Literal["reference_number", "unmatched"]
    comparison_status: Literal[
        "aligned", "changed", "acd_only", "singapore_only", "ambiguous"
    ]
    field_differences: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    candidate_matches: list[str] = Field(default_factory=list)
    professional_review_required: bool
    material_difference: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class SubstanceRecord(StrictModel):
    substance_id: str
    source_document: str
    source_version: str | None
    source_hash: str
    source_snapshot_generated_at: str | None
    regulatory_section: str
    reference_number: str
    original_substance_name: str
    normalized_substance_name: str
    cas_numbers: list[str] = Field(default_factory=list)
    identifiers_raw: str | None = None
    malformed_identifiers: list[str] = Field(default_factory=list)
    source_pages: list[int]
    raw_record_id: str
    active: bool = True

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from data_pipeline.scripts.normalize import CAS_STRUCTURE_RE, cas_is_valid

from .formulation import FormulationIngredientRequest, FormulationRequest
from .formulation import ProductApplicabilityFacts
from .screening import RegulatedFunction, StrictModel


FiniteNonNegativeFloat = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class DocumentRole(StrEnum):
    FINISHED_PRODUCT_FORMULATION = "finished_product_formulation"
    INGREDIENT_LIST = "ingredient_list"
    SUPPLIER_COMPOSITION = "supplier_composition"
    SDS_MSDS = "sds_msds"
    TECHNICAL_DOCUMENT = "technical_document"
    UNKNOWN = "unknown"


class DocumentProcessingStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    CLASSIFYING = "classifying"
    EXTRACTING = "extracting"
    NEEDS_CONFIRMATION = "needs_confirmation"
    READY = "ready"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class SupplierDocumentLibraryStatus(StrEnum):
    PROCESSING = "processing"
    AVAILABLE = "available"
    NEEDS_CONFIRMATION = "needs_confirmation"
    ARCHIVED = "archived"
    FAILED = "failed"


class CompositionQuantityKind(StrEnum):
    EXACT = "exact"
    RANGE = "range"
    UPPER_BOUND = "upper_bound"
    LOWER_BOUND = "lower_bound"
    APPROXIMATE = "approximate"
    CODED_RANGE = "coded_range"
    REMAINDER_TO_TOTAL = "remainder_to_total"
    UNKNOWN = "unknown"


class DisclosureStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ConfirmationStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    NEEDS_CONFIRMATION = "needs_confirmation"


class AssemblyCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class AssemblyIssueSeverity(StrEnum):
    ERROR = "error"
    REVIEW_REQUIRED = "review_required"
    WARNING = "warning"


class AssemblyIssueScope(StrEnum):
    ASSEMBLY = "assembly"
    DOCUMENT = "document"
    MATERIAL = "material"
    CONSTITUENT = "constituent"
    ASSOCIATION = "association"
    CALCULATION = "calculation"


class DocumentSourceEvidence(StrictModel):
    document_id: str
    page: int | None = Field(default=None, ge=1)
    source_row: int | None = Field(default=None, ge=1)
    source_column: str | None = None
    source_snippet: str | None = None
    raw_value: str | None = None


class DocumentRoleEvidence(StrictModel):
    role: DocumentRole
    confidence: Literal["confirmed", "high", "medium", "low"]
    page: int | None = Field(default=None, ge=1)
    source_snippet: str | None = None
    reasons: list[str] = Field(default_factory=list)


class DocumentClassification(StrictModel):
    proposed_roles: list[DocumentRoleEvidence] = Field(default_factory=list)
    supplier_name: str | None = None
    trade_name: str | None = None
    product_code: str | None = None
    document_revision_label: str | None = None
    possible_formulation_ids: list[str] = Field(default_factory=list)
    multiple_products_detected: bool = False
    recommended_extraction_schema: Literal[
        "finished_product_formulation",
        "ingredient_list",
        "supplier_composition",
        "sds_composition",
        "mixed",
        "unknown",
    ] = "unknown"
    questions: list[str] = Field(default_factory=list)


class DocumentExtraction(StrictModel):
    document_id: str
    classification: DocumentClassification
    supplier_materials: list["SupplierMaterial"] = Field(default_factory=list)
    direct_ingredients: list["DirectIngredient"] = Field(default_factory=list)
    legends: list["CompositionLegend"] = Field(default_factory=list)
    unresolved_source_rows: list[DocumentSourceEvidence] = Field(default_factory=list)
    extraction_schema_version: str


class CompositionQuantity(StrictModel):
    kind: CompositionQuantityKind
    value: FiniteNonNegativeFloat | None = None
    lower: FiniteNonNegativeFloat | None = None
    upper: FiniteNonNegativeFloat | None = None
    lower_inclusive: bool | None = None
    upper_inclusive: bool | None = None
    unit: str | None = None
    basis: str | None = None
    preparation_stage: str | None = None
    quantity_scope: Literal["supplier_material", "finished_product"] | None = None
    raw_text: str | None = None
    reported_code: str | None = None
    legend_entry_id: str | None = None
    approximate: bool = False

    @field_validator("unit", "basis", "preparation_stage", "reported_code", "legend_entry_id")
    @classmethod
    def strip_optional_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_shape(self) -> "CompositionQuantity":
        if self.kind in {CompositionQuantityKind.EXACT, CompositionQuantityKind.APPROXIMATE}:
            if self.value is None:
                raise ValueError(f"{self.kind.value} quantity requires value")
        elif self.kind == CompositionQuantityKind.RANGE:
            if self.lower is None or self.upper is None:
                raise ValueError("Range quantity requires lower and upper")
            if self.lower > self.upper:
                raise ValueError("Range lower cannot exceed upper")
        elif self.kind == CompositionQuantityKind.UPPER_BOUND and self.upper is None:
            raise ValueError("Upper-bound quantity requires upper")
        elif self.kind == CompositionQuantityKind.LOWER_BOUND and self.lower is None:
            raise ValueError("Lower-bound quantity requires lower")
        elif self.kind == CompositionQuantityKind.CODED_RANGE and not self.reported_code:
            raise ValueError("Coded quantity requires reported_code")
        elif self.kind == CompositionQuantityKind.REMAINDER_TO_TOTAL:
            if self.value is None:
                raise ValueError("Remainder-to-total quantity requires target value")
        return self


class CompositionLegendEntry(StrictModel):
    entry_id: str
    code: str
    raw_definition: str
    normalized_quantity: CompositionQuantity
    evidence: list[DocumentSourceEvidence] = Field(default_factory=list)

    @field_validator("entry_id", "code", "raw_definition")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Legend entry fields cannot be blank")
        return stripped


class CompositionLegend(StrictModel):
    legend_id: str
    document_id: str
    document_revision: str | None = None
    name: str | None = None
    entries: list[CompositionLegendEntry] = Field(min_length=1)


class MaterialConstituent(StrictModel):
    constituent_id: str
    submitted_name: str
    cas_number: str | None = None
    composition_quantity: CompositionQuantity | None = None
    source_evidence: list[DocumentSourceEvidence] = Field(default_factory=list)
    verified_identity_group: str | None = None
    regulated_functions: list[RegulatedFunction] = Field(default_factory=list)
    role_label: str | None = None
    user_edits: dict[str, Any] = Field(default_factory=dict)

    @field_validator("constituent_id", "submitted_name")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Constituent fields cannot be blank")
        return stripped

    @field_validator("cas_number")
    @classmethod
    def validate_cas_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not CAS_STRUCTURE_RE.fullmatch(normalized) or not cas_is_valid(normalized):
            raise ValueError("CAS number must have valid syntax and checksum")
        return normalized


class SupplierMaterial(StrictModel):
    material_id: str
    trade_name: str
    supplier_name: str | None = None
    product_code: str | None = None
    finished_product_usage: CompositionQuantity | None = None
    attached_document_ids: list[str] = Field(default_factory=list)
    governing_document_id: str | None = None
    conflicting_document_ids: list[str] = Field(default_factory=list)
    constituents: list[MaterialConstituent] = Field(default_factory=list)
    removed_constituent_ids: list[str] = Field(default_factory=list)
    disclosure_status: DisclosureStatus = DisclosureStatus.UNKNOWN
    confirmation_status: ConfirmationStatus = ConfirmationStatus.PROPOSED

    @field_validator("material_id", "trade_name")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Material fields cannot be blank")
        return stripped


class DirectIngredient(StrictModel):
    ingredient_id: str
    ingredient: FormulationIngredientRequest
    source_document_id: str
    source_evidence: list[DocumentSourceEvidence] = Field(default_factory=list)
    verified_identity_group: str | None = None


class CalculatedContribution(StrictModel):
    contribution_id: str
    source_type: Literal["material_constituent", "direct_ingredient"]
    source_material_id: str | None = None
    source_constituent_id: str | None = None
    source_direct_ingredient_id: str | None = None
    governing_document_id: str
    verified_identity_group: str
    display_name: str
    cas_number: str | None = None
    regulated_functions: list[RegulatedFunction] = Field(default_factory=list)
    composition_quantity: CompositionQuantity | None = None
    material_usage: CompositionQuantity | None = None
    finished_product_quantity: CompositionQuantity
    calculation_formula: str
    source_evidence: list[DocumentSourceEvidence] = Field(default_factory=list)


class AggregatedIngredient(StrictModel):
    verified_identity_group: str
    display_name: str
    cas_number: str | None = None
    regulated_functions: list[RegulatedFunction] = Field(default_factory=list)
    aggregate_quantity: CompositionQuantity
    contributions: list[CalculatedContribution] = Field(min_length=1)
    completeness: AssemblyCompleteness


class AssemblyIssue(StrictModel):
    issue_id: str
    code: Literal[
        "unresolved_raw_material",
        "incomplete_supplier_disclosure",
        "material_usage_missing",
        "constituent_concentration_missing",
        "constituent_identity_unresolved",
        "constituent_identity_ambiguous",
        "document_association_unconfirmed",
        "duplicate_document",
        "composition_statement_conflict",
        "missing_legend",
        "unknown_legend_code",
        "incompatible_quantity_basis",
        "invalid_concentration_bound",
        "impossible_composition_total",
        "unverified_identity_aggregation",
        "calculation_withheld",
    ]
    severity: AssemblyIssueSeverity
    scope: AssemblyIssueScope
    message: str
    reviewer_action: str
    blocking_for_calculation: bool = False
    blocking_for_full_evaluation: bool = True
    document_ids: list[str] = Field(default_factory=list)
    material_ids: list[str] = Field(default_factory=list)
    constituent_ids: list[str] = Field(default_factory=list)
    evidence: list[DocumentSourceEvidence] = Field(default_factory=list)


class AssemblyResult(StrictModel):
    assembly_revision: int = Field(ge=0)
    completeness: AssemblyCompleteness
    included_ingredients: list[AggregatedIngredient] = Field(default_factory=list)
    unresolved_raw_materials: list[str] = Field(default_factory=list)
    incomplete_disclosures: list[str] = Field(default_factory=list)
    unresolved_associations: list[str] = Field(default_factory=list)
    excluded_items: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[AssemblyIssue] = Field(default_factory=list)
    evaluated_scope: dict[str, Any] = Field(default_factory=dict)
    calculation_snapshot: dict[str, Any] = Field(default_factory=dict)


class PreparedAssembly(StrictModel):
    result: AssemblyResult
    formulation: FormulationRequest | None = None


class FormulationAssemblyState(StrictModel):
    """Reviewer-editable canonical state for multi-document assembly."""

    direct_ingredients: list[DirectIngredient] = Field(default_factory=list)
    materials: list[SupplierMaterial] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    source_document_snapshots: dict[str, str] = Field(default_factory=dict)
    formulation_name: str | None = None
    product_context: str | None = None
    product_applicability: ProductApplicabilityFacts = Field(default_factory=ProductApplicabilityFacts)

    @field_validator("formulation_name", "product_context")
    @classmethod
    def strip_optional_state_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SavedSupplierDocument(StrictModel):
    supplier_document_id: UUID
    organisation_id: UUID
    original_filename: str
    sha256: str
    supplier_name: str | None = None
    trade_name: str | None = None
    product_code: str | None = None
    document_revision_label: str | None = None
    document_date: str | None = None
    detected_roles: list[DocumentRoleEvidence] = Field(default_factory=list)
    confirmed_roles: list[DocumentRole] = Field(default_factory=list)
    extraction_schema_version: str | None = None
    processing_key: str | None = None
    supersedes_supplier_document_id: UUID | None = None
    library_status: SupplierDocumentLibraryStatus


class SupplierDocumentAttachment(StrictModel):
    formulation_document_id: UUID
    formulation_version_id: UUID
    supplier_document_id: UUID
    attached_extraction_key: str
    formulation_local_roles: list[DocumentRole] = Field(default_factory=list)
    governing_for_material: bool = False
    attached_by: UUID


DocumentExtraction.model_rebuild()

from __future__ import annotations

from pydantic import Field, model_validator

from .screening import SingaporeLinkageStatus, StrictModel


class IngredientSearchResult(StrictModel):
    ingredient_id: str
    canonical_name: str
    display_name: str
    identity_source: str
    source_document: str
    source_version: str
    source_entries: list[int]
    source_pages: list[int]
    raw_record_ids: list[str]


class IngredientSearchResponse(StrictModel):
    query: str
    dataset_version: str
    accepted_baseline_sha256: str
    results: list[IngredientSearchResult] = Field(default_factory=list)


class IdentityCatalogueDataset(StrictModel):
    available: bool
    dataset_version: str | None = None
    accepted_baseline_sha256: str | None = None
    source_name: str | None = None
    source_role: str | None = None
    ingredient_count: int | None = None
    error: str | None = None


class IdentityLinkageDataset(StrictModel):
    available: bool
    dataset_version: str | None = None
    accepted_baseline_sha256: str | None = None
    identity_dataset_version: str | None = None
    singapore_regulatory_baseline: str | None = None
    screened_scope: list[str] = Field(default_factory=list)
    accepted_records: int | None = None
    linked: int | None = None
    verified_not_represented: int | None = None
    unresolved: int | None = None
    error: str | None = None


class SingaporeIdentityLinkageRecord(StrictModel):
    catalogue_ingredient_id: str
    catalogue_canonical_name: str
    identity_dataset_version: str
    singapore_regulatory_baseline: str
    screened_scope: list[str] = Field(min_length=1)
    status: SingaporeLinkageStatus

    @model_validator(mode="after")
    def require_bounded_verified_absence(self) -> "SingaporeIdentityLinkageRecord":
        if self.status == SingaporeLinkageStatus.NOT_APPLICABLE:
            raise ValueError("Catalogue linkage records cannot use not_applicable")
        if self.status == SingaporeLinkageStatus.VERIFIED_NOT_REPRESENTED:
            required = {
                "Third Schedule Part I", "Third Schedule Part II", "Third Schedule Part III",
                "Third Schedule Part IV", "Third Schedule Part V",
            }
            if set(self.screened_scope) != required:
                raise ValueError(
                    "verified_not_represented must be bound to Third Schedule Parts I-V"
                )
        return self

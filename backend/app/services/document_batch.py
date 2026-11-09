from __future__ import annotations

from backend.app.services.agent_csv import ParsedCSV
from backend.app.services.document_classifier import classify_document


class DocumentBatchError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def select_primary_formulation(
    documents: list[ParsedCSV | None],
    *,
    legacy_first_file: bool = False,
) -> int:
    """Select one formulation source without treating supplier PDFs as products."""
    if not documents:
        raise DocumentBatchError(
            "document_batch_invalid",
            "Upload at least one formulation or ingredient-list document.",
        )
    if legacy_first_file:
        return 0

    finished_candidates: list[int] = []
    ingredient_list_candidates: list[int] = []
    supplier_candidates: list[int] = []
    for index, document in enumerate(documents):
        if document is None:
            continue
        roles = {item.role.value for item in classify_document(document).proposed_roles}
        if "finished_product_formulation" in roles:
            finished_candidates.append(index)
        elif "ingredient_list" in roles:
            ingredient_list_candidates.append(index)
        elif roles & {"supplier_composition", "sds_msds"}:
            supplier_candidates.append(index)

    if len(finished_candidates) == 1:
        return finished_candidates[0]
    if len(finished_candidates) > 1:
        raise DocumentBatchError(
            "multiple_finished_formulations",
            "More than one possible finished formulation was found. Upload one formulation per version and attach its supplier documents together.",
        )
    if len(ingredient_list_candidates) == 1:
        return ingredient_list_candidates[0]
    if len(ingredient_list_candidates) > 1:
        raise DocumentBatchError(
            "multiple_ingredient_lists",
            "More than one possible ingredient list was found without a clear finished formulation. Select one governing formulation or split the documents into separate versions.",
        )
    if supplier_candidates:
        raise DocumentBatchError(
            "supplier_document_without_formulation",
            "Regulens recognised an SDS/MSDS or supplier composition, but no finished-product formulation. Keep the supplier file selected and add the formulation that states how much of the material is used.",
        )
    raise DocumentBatchError(
        "finished_formulation_not_found",
        "No finished-product formulation or ingredient list could be identified in this upload.",
    )

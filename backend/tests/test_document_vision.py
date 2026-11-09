from __future__ import annotations

from backend.app.services.document_vision import (
    VisionCompositionRow,
    VisionDocumentFacts,
    VisionLegendLine,
    facts_to_parsed,
)
from backend.app.services.document_classifier import classify_document


def test_vision_schema_is_compatible_with_openai_strict_structured_outputs() -> None:
    schema = VisionDocumentFacts.model_json_schema()
    assert set(schema["required"]) == set(schema["properties"])
    row_schema = schema["$defs"]["VisionCompositionRow"]
    assert set(row_schema["required"]) == set(row_schema["properties"])


def test_visible_facts_preserve_page_snippet_and_quantity_text() -> None:
    facts = VisionDocumentFacts(
        document_role="sds_msds",
        supplier_name="Example Supplier",
        trade_name="MATRIXYL 3000",
        product_code=None,
        document_revision_label=None,
        multiple_products_detected=False,
        composition_rows=[VisionCompositionRow(
            ingredient_name="GLYCERIN",
            cas_number="56-81-5",
            concentration_text="C",
            continues_previous_name=False,
            page=4,
            source_snippet="GLYCERIN 56-81-5 C",
        )],
        legend_lines=[VisionLegendLine(text="C = 25-50%", page=3)],
    )

    parsed = facts_to_parsed("supplier.pdf", facts, page_count=6)

    assert parsed.page_count == 6
    assert ("C = 25-50%",) in parsed.rows
    row_index = parsed.rows.index(("GLYCERIN", "56-81-5", "C"))
    assert parsed.row_pages[row_index] == 4
    assert parsed.row_snippets[row_index] == "GLYCERIN 56-81-5 C"


def test_vision_multiple_product_signal_survives_deterministic_classification() -> None:
    facts = VisionDocumentFacts(
        document_role="supplier_composition",
        supplier_name=None,
        trade_name=None,
        product_code=None,
        document_revision_label=None,
        multiple_products_detected=True,
        composition_rows=[VisionCompositionRow(
            ingredient_name="GLYCERIN",
            cas_number=None,
            concentration_text="10%",
            continues_previous_name=False,
            page=2,
            source_snippet="GLYCERIN 10%",
        )],
        legend_lines=[],
    )

    parsed = facts_to_parsed("multi-product.pdf", facts, page_count=2)
    classification = classify_document(parsed)

    assert classification.multiple_products_detected is True
    assert classification.questions == [
        "This document appears to describe more than one product. Select or split the applicable product."
    ]


def test_vision_adapter_preserves_role_and_merges_conservative_wrapped_name() -> None:
    facts = VisionDocumentFacts(
        document_role="sds_msds",
        supplier_name=None,
        trade_name="Example Blend",
        product_code=None,
        document_revision_label=None,
        multiple_products_detected=False,
        composition_rows=[
            VisionCompositionRow(
                ingredient_name="First name fragment",
                cas_number="9006-65-9",
                concentration_text="1-5%",
                continues_previous_name=False,
                page=2,
                source_snippet="First name fragment 9006-65-9 1-5%",
            ),
            VisionCompositionRow(
                ingredient_name="second fragment",
                cas_number=None,
                concentration_text=None,
                continues_previous_name=False,
                page=2,
                source_snippet="second fragment",
            ),
        ],
        legend_lines=[],
    )

    parsed = facts_to_parsed("supplier.pdf", facts, page_count=2)
    classification = classify_document(parsed)

    assert parsed.rows[0] == ("Material Safety Data Sheet",)
    assert ("First name fragment second fragment", "9006-65-9", "1-5%") in parsed.rows
    assert sum(row[0].casefold().endswith("fragment") for row in parsed.rows) == 1
    assert "sds_msds" in {item.role.value for item in classification.proposed_roles}
    assert classification.recommended_extraction_schema == "sds_composition"

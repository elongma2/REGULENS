from __future__ import annotations

from types import SimpleNamespace

from backend.app.services.document_vision import (
    OpenAIDocumentVisionExtractor,
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
            unit_text=None,
            function_or_role=None,
            notes=None,
            extraction_uncertainty=None,
            source_row_label=None,
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
            unit_text=None,
            function_or_role=None,
            notes=None,
            extraction_uncertainty=None,
            source_row_label=None,
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


def test_formulation_vision_preserves_layout_fields_ranges_and_uncertainty() -> None:
    facts = VisionDocumentFacts(
        document_role="finished_product_formulation",
        supplier_name=None,
        trade_name="LuminaGlow Serum",
        product_code="LG-3",
        document_revision_label="V3",
        multiple_products_detected=False,
        composition_rows=[VisionCompositionRow(
            ingredient_name="AquaRenew C7 Complex",
            cas_number=None,
            concentration_text="5 - 10",
            unit_text="%",
            function_or_role="Humectant complex",
            notes="Add below 40 C",
            extraction_uncertainty="The first digit is visually faint.",
            source_row_label="Row 17",
            continues_previous_name=False,
            page=2,
            source_snippet="AquaRenew C7 Complex | 5 - 10 | % | Humectant complex",
        )],
        legend_lines=[],
    )

    parsed = facts_to_parsed("messy-scan.pdf", facts, page_count=3)

    header = parsed.rows.index((
        "Ingredient / Trade Name",
        "CAS No.",
        "Concentration",
        "Unit",
        "Function / Role",
        "Notes",
        "Extraction uncertainty",
        "Source row",
    ))
    data = parsed.rows[header + 1]
    assert data == (
        "AquaRenew C7 Complex",
        "",
        "5 - 10",
        "%",
        "Humectant complex",
        "Add below 40 C",
        "The first digit is visually faint.",
        "Row 17",
    )
    assert parsed.delimiter == "vision"
    assert parsed.row_pages[header + 1] == 2
    assert parsed.row_snippets[header + 1] == (
        "AquaRenew C7 Complex | 5 - 10 | % | Humectant complex"
    )
    classification = classify_document(parsed)
    assert "finished_product_formulation" in {
        item.role.value for item in classification.proposed_roles
    }


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
                unit_text=None,
                function_or_role=None,
                notes=None,
                extraction_uncertainty=None,
                source_row_label=None,
                continues_previous_name=False,
                page=2,
                source_snippet="First name fragment 9006-65-9 1-5%",
            ),
            VisionCompositionRow(
                ingredient_name="second fragment",
                cas_number=None,
                concentration_text=None,
                unit_text=None,
                function_or_role=None,
                notes=None,
                extraction_uncertainty=None,
                source_row_label=None,
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


def test_image_only_pdf_is_processed_in_bounded_batches_across_all_pages(monkeypatch) -> None:
    first = VisionDocumentFacts(
        document_role="supplier_composition",
        supplier_name="Example Supplier",
        trade_name="Example Blend",
        product_code="EX-1",
        document_revision_label="Rev A",
        multiple_products_detected=False,
        composition_rows=[VisionCompositionRow(
            ingredient_name="GLYCERIN",
            cas_number="56-81-5",
            concentration_text="20%",
            unit_text=None,
            function_or_role=None,
            notes=None,
            extraction_uncertainty=None,
            source_row_label=None,
            continues_previous_name=False,
            page=8,
            source_snippet="GLYCERIN 56-81-5 20%",
        )],
        legend_lines=[],
    )
    second = VisionDocumentFacts(
        document_role="unknown",
        supplier_name=None,
        trade_name=None,
        product_code=None,
        document_revision_label=None,
        multiple_products_detected=False,
        composition_rows=[VisionCompositionRow(
            ingredient_name="AQUA",
            cas_number="7732-18-5",
            concentration_text="80%",
            unit_text=None,
            function_or_role=None,
            notes=None,
            extraction_uncertainty=None,
            source_row_label=None,
            continues_previous_name=False,
            # Deliberately batch-local; the adapter must rebase it to page 9.
            page=1,
            source_snippet="AQUA 7732-18-5 80%",
        )],
        legend_lines=[],
    )
    outputs = iter([first, second])
    calls: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            facts = next(outputs)
            return SimpleNamespace(
                output_text=facts.model_dump_json(),
                id=f"response-{len(calls)}",
                model="cheap-vision-model",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("backend.app.services.document_vision.OpenAI", FakeClient)
    monkeypatch.setattr(
        "backend.app.services.document_vision._render_pdf",
        lambda content, page_limit: (["encoded"] * 9, 9),
    )

    extraction = OpenAIDocumentVisionExtractor(
        "test-key", "cheap-vision-model", page_limit=50, batch_pages=8,
    ).extract_pdf(
        "scan.pdf",
        b"pdf",
        expected_role="finished_product_formulation",
    )

    assert len(calls) == 2
    assert extraction.parsed.page_count == 9
    glycerin_index = extraction.parsed.rows.index(("GLYCERIN", "56-81-5", "20%"))
    aqua_index = extraction.parsed.rows.index(("AQUA", "7732-18-5", "80%"))
    assert extraction.parsed.row_pages[glycerin_index] == 8
    assert extraction.parsed.row_pages[aqua_index] == 9
    assert extraction.diagnostics["model_calls"] == 2
    assert extraction.diagnostics["total_tokens"] == 30
    assert "Product Formulation section" in calls[0]["input"][0]["content"][0]["text"]

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.models.document_intake import (
    CompositionQuantityKind,
    DisclosureStatus,
    DocumentRole,
)
from backend.app.services.agent_csv import ParsedCSV, parse_formulation_upload
from backend.app.services.document_classifier import classify_document
from backend.app.services.document_extraction import extract_document


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "trade_materials"


def _parsed(
    rows: list[tuple[str, ...]],
    *,
    filename: str = "document.csv",
    pages: list[int | None] | None = None,
) -> ParsedCSV:
    row_pages = tuple(pages or [])
    return ParsedCSV(
        filename=filename,
        delimiter=",",
        rows=tuple(rows),
        source_format="pdf" if filename.endswith(".pdf") else "structured_grid",
        row_pages=row_pages,
        row_snippets=tuple(" | ".join(row) for row in rows) if row_pages else (),
        page_count=max((page or 0 for page in row_pages), default=0) or None,
    )


def test_classifies_supplier_composition_from_content_not_filename() -> None:
    parsed = _parsed([
        ("Supplier: Example Materials Pte Ltd",),
        ("Product Name: OPTASENSE RMA",),
        ("INCI Name", "CAS No.", "FDA Code"),
        ("GLYCERIN", "56-81-5", "C"),
    ], filename="random-upload.pdf", pages=[1, 1, 1, 1])

    classification = classify_document(parsed)

    assert DocumentRole.SUPPLIER_COMPOSITION in {
        evidence.role for evidence in classification.proposed_roles
    }
    assert classification.trade_name == "OPTASENSE RMA"
    assert classification.supplier_name == "Example Materials Pte Ltd"
    assert classification.recommended_extraction_schema == "supplier_composition"


def test_classifies_and_extracts_vertically_flattened_supplier_composition() -> None:
    parsed = _parsed([
        ("Example Blend - Supplier Composition Statement",),
        ("Supplier Example Materials Pte Ltd",),
        ("Trade name Example Blend",),
        ("Product code EB-70",),
        ("Document revision Rev 2",),
        ("Constituent composition",),
        ("INCI name",),
        ("CAS number",),
        ("Content (% w/w)",),
        ("PHENOXYETHANOL",),
        ("122-99-6",),
        ("70%",),
        ("GLYCERIN",),
        ("56-81-5",),
        ("20-30%",),
        ("Interpretation note",),
        ("Percentages describe the supplier material.",),
    ], filename="vertical.pdf", pages=[1] * 17)

    classification = classify_document(parsed)
    extraction = extract_document(parsed, document_id="vertical")

    assert classification.recommended_extraction_schema == "supplier_composition"
    assert classification.supplier_name == "Example Materials Pte Ltd"
    assert classification.trade_name == "Example Blend"
    assert classification.product_code == "EB-70"
    assert classification.document_revision_label == "Rev 2"
    assert extraction.direct_ingredients == []
    assert [row.submitted_name for row in extraction.supplier_materials[0].constituents] == [
        "PHENOXYETHANOL",
        "GLYCERIN",
    ]
    assert extraction.supplier_materials[0].constituents[0].composition_quantity.value == 70
    assert extraction.supplier_materials[0].constituents[1].composition_quantity.lower == 20
    assert extraction.supplier_materials[0].constituents[1].composition_quantity.upper == 30


def test_finished_formula_wins_over_incidental_supplier_language() -> None:
    parsed = _parsed([
        ("Finished Product Formulation - Pilot Serum",),
        ("One formula mixing direct ingredients with supplier trade-name raw materials.",),
        ("Product: Leave-on facial serum",),
        ("Submitted material / ingredient CAS if supplied Finished product Entry type",),
        ("usage",),
        ("GLYCERIN 56-81-5 3% Direct INCI",),
        ("LumiMatrix 3000 - 4% Supplier trade",),
    ], filename="finished-formula.pdf", pages=[1] * 7)

    classification = classify_document(parsed)
    extraction = extract_document(parsed, document_id="formula")

    assert classification.recommended_extraction_schema == "finished_product_formulation"
    assert classification.multiple_products_detected is False
    assert extraction.supplier_materials == []
    assert [row.ingredient.name for row in extraction.direct_ingredients] == [
        "GLYCERIN",
        "LumiMatrix 3000",
    ]
    assert (
        extraction.direct_ingredients[0].ingredient.concentration.preparation_stage.value
        == "finished_product"
    )


def test_extracts_document_local_code_legend_without_equals_sign() -> None:
    parsed = _parsed([
        ("Supplier: Example Materials",),
        ("Product Name: OPTASENSE RMA",),
        ("FDA concentration legend: A >75%; B 50-75%; C 25-50%",),
        ("INCI Name", "CAS No.", "FDA Code"),
        ("GLYCERIN", "56-81-5", "C"),
    ])

    extraction = extract_document(parsed, document_id="doc-1")

    assert extraction.legends
    entries = {entry.code: entry.normalized_quantity for entry in extraction.legends[0].entries}
    assert entries["C"].kind == CompositionQuantityKind.RANGE
    assert entries["C"].lower == 25
    assert entries["C"].upper == 50
    constituent = extraction.supplier_materials[0].constituents[0]
    assert constituent.composition_quantity is not None
    assert constituent.composition_quantity.kind == CompositionQuantityKind.CODED_RANGE
    assert constituent.composition_quantity.reported_code == "C"


def test_extracts_separate_supplier_lower_and_upper_columns() -> None:
    parsed = _parsed([
        ("Supplier: Example Materials",),
        ("Product Name: VISCOPTIMA SE-LQ",),
        ("INCI Name", "CAS No.", "Lower Limit", "Upper Limit", "Unit"),
        ("SODIUM POLYACRYLATE", "9003-04-7", "25", "50", "%"),
    ])

    extraction = extract_document(parsed, document_id="doc-2")

    quantity = extraction.supplier_materials[0].constituents[0].composition_quantity
    assert quantity is not None
    assert quantity.kind == CompositionQuantityKind.RANGE
    assert quantity.lower == 25
    assert quantity.upper == 50
    assert quantity.lower_inclusive is None
    assert quantity.upper_inclusive is None
    assert quantity.unit == "percent"
    assert quantity.quantity_scope == "supplier_material"


def test_sds_text_extraction_is_limited_to_section_three() -> None:
    parsed = _parsed([
        ("SAFETY DATA SHEET",),
        ("Product Name: SiCare 2315F3",),
        ("SECTION 2 Hazards identification",),
        ("Emergency reference 7732-18-5",),
        ("SECTION 3 Composition / information on ingredients",),
        ("Water 7732-18-5 40-60%",),
        ("Glycerin 56-81-5 10-20%",),
        ("SECTION 4 First aid measures",),
        ("Reference substance 122-99-6 1%",),
    ], filename="sicare.pdf", pages=[1, 1, 1, 1, 2, 2, 2, 3, 3])

    extraction = extract_document(parsed, document_id="doc-3")

    material = extraction.supplier_materials[0]
    assert [item.submitted_name for item in material.constituents] == ["Water", "Glycerin"]
    assert [item.cas_number for item in material.constituents] == ["7732-18-5", "56-81-5"]
    assert all(item.source_evidence[0].page == 2 for item in material.constituents)


def test_direct_inci_grid_remains_a_direct_ingredient_workflow() -> None:
    parsed = _parsed([
        ("INCI Name", "CAS No.", "Concentration"),
        ("GLYCERIN", "56-81-5", "5%"),
    ], filename="formulation.csv")

    extraction = extract_document(parsed, document_id="doc-4")

    assert not extraction.supplier_materials
    assert len(extraction.direct_ingredients) == 1
    ingredient = extraction.direct_ingredients[0].ingredient
    assert ingredient.name == "GLYCERIN"
    assert ingredient.cas_number == "56-81-5"
    assert ingredient.concentration is not None
    assert ingredient.concentration.value == 5
    assert ingredient.concentration.unit.value == "percent"


def test_multiple_product_labels_require_confirmation() -> None:
    parsed = _parsed([
        ("Product Name: Serum A",),
        ("Product Name: Serum B",),
        ("INCI Name", "Concentration"),
        ("GLYCERIN", "5%"),
    ])

    classification = classify_document(parsed)

    assert classification.multiple_products_detected is True
    assert classification.possible_formulation_ids == ["Serum A", "Serum B"]
    assert classification.trade_name is None
    assert classification.questions


def test_extracts_flattened_optasense_codes_with_complete_local_legend() -> None:
    parsed = _parsed([
        ("Percentage Composition Statement for OPTASENSE RMA EN80159",),
        ("Component (INCI Name) Content (FDA Code)",),
        ("SODIUM POLYACRYLATE C",),
        ("CAPRYLIC/CAPRIC TRIGLYCERIDE D",),
        ("where FDA Codes: A >75%",),
        ("B 50-75%",), ("C 25-50%",), ("D 10-25%",),
        ("E 5-10%",), ("F 1-5%",), ("G 0.1-1%",), ("H <0.1%",),
    ], filename="optasense.pdf", pages=[1] * 12)

    extraction = extract_document(parsed, document_id="optasense")

    assert extraction.classification.product_code == "EN80159"
    assert [item.submitted_name for item in extraction.supplier_materials[0].constituents] == [
        "SODIUM POLYACRYLATE", "CAPRYLIC/CAPRIC TRIGLYCERIDE",
    ]
    assert {entry.code for entry in extraction.legends[0].entries} == set("ABCDEFGH")
    legend_values = {
        entry.code: (
            entry.normalized_quantity.kind.value,
            entry.normalized_quantity.lower,
            entry.normalized_quantity.upper,
        )
        for entry in extraction.legends[0].entries
    }
    assert legend_values == {
        "A": ("lower_bound", 75.0, None),
        "B": ("range", 50.0, 75.0),
        "C": ("range", 25.0, 50.0),
        "D": ("range", 10.0, 25.0),
        "E": ("range", 5.0, 10.0),
        "F": ("range", 1.0, 5.0),
        "G": ("range", 0.1, 1.0),
        "H": ("upper_bound", None, 0.1),
    }


def test_extracts_flattened_supplier_ranges_and_continuation_name() -> None:
    parsed = _parsed([
        ("Statement Regarding the Composition of Product:VISCOPTIMA SE-LQ EN00297",),
        ("INCI Name Lower Limit Upper Limit Units of measurement",),
        ("SODIUM POLYACRYLATE 50 100 %",),
        ("PPG-3 Benzyl Ether 5 10 %",),
        ("Myristate",),
        ("Non-warranty",),
    ], filename="viscoptima.pdf", pages=[1] * 6)

    extraction = extract_document(parsed, document_id="viscoptima")
    rows = extraction.supplier_materials[0].constituents

    assert [item.submitted_name for item in rows] == [
        "SODIUM POLYACRYLATE", "PPG-3 Benzyl Ether Myristate",
    ]
    assert rows[1].composition_quantity.lower == 5
    assert rows[1].composition_quantity.upper == 10


def test_extracts_flattened_matrixyl_qsp_approximate_and_maximum_rows() -> None:
    parsed = _parsed([
        ("PRODUCT INFORMATION",),
        ("MATRIXYL 3000 MBAL",),
        ("Item code: SE28264",),
        ("INCI Name/CAS Nr/EINECS Nr/Composition:",),
        ("Glycerin qsp 100 56-81-5 200-289-5",),
        ("Water (Aqua) approx. 25 7732-18-5 231-791-2",),
        ("Sodium Lactate max. 1 72-17-3 200-772-0",),
    ], filename="matrixyl.pdf", pages=[1] * 7)

    extraction = extract_document(parsed, document_id="matrixyl")
    rows = extraction.supplier_materials[0].constituents

    assert extraction.classification.trade_name == "MATRIXYL 3000 MBAL"
    assert extraction.classification.product_code == "SE28264"
    assert [item.composition_quantity.kind for item in rows] == [
        CompositionQuantityKind.REMAINDER_TO_TOTAL,
        CompositionQuantityKind.APPROXIMATE,
        CompositionQuantityKind.UPPER_BOUND,
    ]


def test_partial_disclosure_keeps_no_cas_rows_and_unresolved_carrier() -> None:
    parsed = _parsed([
        ("Supplier: Example Botanicals",),
        ("Trade name: Partial Blend",),
        ("Disclosure status: PARTIAL - not all constituents are disclosed",),
        ("INCI / ingredient name CAS No. Concentration",),
        ("GLYCERIN 56-81-5 20-30%",),
        ("PROPRIETARY BOTANICAL FRACTION Not disclosed 5-10%",),
        ("UNDISCLOSED CARRIER SYSTEM Not disclosed Balance not disclosed",),
        ("Declaration",),
    ], filename="partial.pdf", pages=[1] * 8)

    extraction = extract_document(parsed, document_id="partial")
    material = extraction.supplier_materials[0]

    assert material.disclosure_status == DisclosureStatus.PARTIAL
    assert [item.submitted_name for item in material.constituents] == [
        "GLYCERIN",
        "PROPRIETARY BOTANICAL FRACTION",
        "UNDISCLOSED CARRIER SYSTEM",
    ]
    assert material.constituents[1].cas_number is None
    assert material.constituents[1].composition_quantity is not None
    assert material.constituents[1].composition_quantity.kind == CompositionQuantityKind.RANGE
    assert material.constituents[2].composition_quantity is None
    assert len(extraction.unresolved_source_rows) == 1


@pytest.mark.parametrize(
    ("filename", "expected_constituents", "expected_legend_entries"),
    [
        ("optasense_composition.csv", 6, 8),
        ("matrixyl_composition.csv", 8, 0),
        ("viscoptima_composition.csv", 4, 0),
        ("sicare_section3.csv", 3, 0),
    ],
)
def test_redacted_pilot_structure_fixtures_remain_extractable(
    filename: str,
    expected_constituents: int,
    expected_legend_entries: int,
) -> None:
    path = FIXTURE_ROOT / filename
    parsed = parse_formulation_upload(path.name, path.read_bytes())
    extraction = extract_document(parsed, document_id=f"fixture:{filename}")

    assert sum(len(material.constituents) for material in extraction.supplier_materials) == expected_constituents
    assert sum(len(legend.entries) for legend in extraction.legends) == expected_legend_entries

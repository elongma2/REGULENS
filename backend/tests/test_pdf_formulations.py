from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.app.models.formulation import FormulationRequest
from backend.app.models.agent import ModelInterpretation
from backend.app.models.screening import Finding
from backend.app.services.agent_csv import CSVUploadError, ParsedCSV, parse_csv_upload
from backend.app.services.concentration import parse_concentration_text
from backend.app.services.formulation import screen_formulation
from backend.app.services.formulation_agent import FormulationAgentService
from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.loader import load_accepted_store


ROOT = Path(__file__).resolve().parents[2]


def _text_pdf(*pages: list[str]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        })
        commands = [b"BT /F1 11 Tf 72 720 Td"]
        for index, line in enumerate(lines):
            if index:
                commands.append(b"0 -18 Td")
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj".encode("latin-1"))
        commands.append(b"ET")
        stream = DecodedStreamObject()
        stream.set_data(b" ".join(commands))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_selectable_text_pdf_preserves_pages_and_multpage_rows():
    parsed = parse_csv_upload(
        "supplier-sds.pdf",
        _text_pdf(
            ["Ingredient CAS Concentration", "Glycerin 56-81-5 5%"],
            ["Ingredient CAS Concentration", "Phenoxyethanol 122-99-6 0.5-1.5%"],
        ),
    )
    assert parsed.source_format == "pdf"
    assert parsed.page_count == 2
    assert parsed.row_pages == (1, 1, 2, 2)
    assert parsed.rows[1] == ("Glycerin 56-81-5 5%",)
    assert "Phenoxyethanol" in parsed.snippet_for_row(4)


def test_image_only_or_blank_pdf_is_rejected_with_actionable_message():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(CSVUploadError, match="Unable to extract text from this PDF"):
        parse_csv_upload("scan.pdf", output.getvalue())


@pytest.mark.parametrize(
    ("raw", "expected_type", "lower", "upper", "inclusive"),
    [
        ("1%", "exact", None, None, None),
        ("0.5–2%", "range", 0.5, 2.0, True),
        ("<1%", "upper_bound", None, 1.0, False),
        ("≤1%", "upper_bound", None, 1.0, True),
        (">0.1%", "lower_bound", 0.1, None, False),
        ("≥0.1%", "lower_bound", 0.1, None, True),
        ("Approximately 1%", "approximate", None, None, None),
        ("Not disclosed", "unknown", None, None, None),
    ],
)
def test_concentration_text_types(raw, expected_type, lower, upper, inclusive):
    parsed = parse_concentration_text(raw)
    assert parsed is not None
    assert parsed.concentration_type.value == expected_type
    assert parsed.lower_bound == lower
    assert parsed.upper_bound == upper
    if expected_type == "upper_bound":
        assert parsed.upper_inclusive is inclusive
    if expected_type == "lower_bound":
        assert parsed.lower_inclusive is inclusive


@pytest.mark.parametrize(
    ("concentration", "finding"),
    [
        ({"concentration_type": "range", "lower_bound": 0.05, "upper_bound": 0.1}, Finding.WITHIN_LIMIT),
        ({"concentration_type": "range", "lower_bound": 0.1, "upper_bound": 0.3}, Finding.PROFESSIONAL_REVIEW),
        ({"concentration_type": "range", "lower_bound": 0.21, "upper_bound": 0.4}, Finding.RESTRICTION_EXCEEDED),
        ({"concentration_type": "upper_bound", "upper_bound": 0.1, "upper_inclusive": False}, Finding.WITHIN_LIMIT),
        ({"concentration_type": "lower_bound", "lower_bound": 0.21, "lower_inclusive": False}, Finding.RESTRICTION_EXCEEDED),
        ({"concentration_type": "approximate", "value": 0.1}, Finding.PROFESSIONAL_REVIEW),
        ({"concentration_type": "unknown"}, Finding.INFORMATION_MISSING),
    ],
)
def test_ranges_are_screened_conservatively(concentration, finding):
    store = load_accepted_store(ROOT)
    catalogue = load_accepted_ingredient_catalog(ROOT)
    payload = {
        **concentration,
        "original_text": "reported value",
        "unit": "percent" if concentration["concentration_type"] != "unknown" else None,
        "basis": None,
        "preparation_stage": "finished_product" if concentration["concentration_type"] != "unknown" else None,
    }
    response = screen_formulation(
        store,
        FormulationRequest.model_validate({
            "ingredients": [{"name": "Tosylchloramide sodium", "concentration": payload}],
        }),
        ingredient_catalog=catalogue,
    )
    assert response.ingredient_results[0].primary_finding == finding


def test_legacy_document_completeness_does_not_change_ingredient_screening():
    store = load_accepted_store(ROOT)
    catalogue = load_accepted_ingredient_catalog(ROOT)
    response = screen_formulation(
        store,
        FormulationRequest.model_validate({
            "source_document_type": "sds_msds",
            "document_completeness": "partial_disclosure",
            "source_filename": "supplier-sds.pdf",
            "ingredients": [{"name": "Benzene"}],
        }),
        ingredient_catalog=catalogue,
    )
    assert "may not contain the complete formulation" not in response.ingredient_results[0].scope_note
    assert response.ingredient_results[0].primary_finding == Finding.PROHIBITED


def test_pdf_agent_preserves_range_and_page_without_completeness_classification():
    from backend.tests.test_agent import interpretation

    source = "Glycerin 56-81-5 0.5-1.5%"
    parsed = ParsedCSV(
        filename="supplier-sds.pdf",
        delimiter="pdf_text",
        rows=(("Section 3 Composition",), (source,)),
        source_format="pdf",
        row_pages=(1, 2),
        row_snippets=("Section 3 Composition", source),
        page_count=2,
    )

    def runner(*_):
        return interpretation(
            [{
                "source_row": 2,
                "source_name": source,
                "interpreted_name": "GLYCERIN",
                "identity_status": "exact_match",
                "source_cas": "56-81-5",
                "source_cas_cell": source,
                "source_concentration": source,
                "concentration_text": "0.5-1.5%",
                "concentration_value": None,
                "concentration_unit": "percent",
                "issues": [],
            }],
            mappings=[
                {"source_column_index": 0, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
                {"source_column_index": 0, "mapped_field": "cas_number", "confidence": "high_confidence"},
                {"source_column_index": 0, "mapped_field": "concentration", "confidence": "high_confidence"},
            ],
            document_assessment={
                "multiple_products_detected": False,
                "reasons": [],
                "sources": [],
            },
        )

    service = FormulationAgentService(
        load_accepted_store(ROOT),
        load_accepted_ingredient_catalog(ROOT),
        model_runner=runner,
    )
    session = service.create(parsed)
    row = session.interpreted_rows[0]
    assert row.source_pages == [2]
    assert row.concentration.concentration_type.value.value == "range"
    assert row.concentration.lower_bound.value == 0.5
    assert row.concentration.upper_bound.value == 1.5
    assert row.cas_number.value == "56-81-5"
    assert all(question.question_type != "document_completeness" for question in session.questions)


def test_pdf_agent_accepts_document_level_stage_and_literal_name_substring():
    from backend.tests.test_agent import interpretation
    from backend.app.models.agent import AgentSessionState, AgentSessionView
    from backend.app.services.formulation_agent import _Session

    ingredient_line = "GLYCERIN 56-81-5 5% Humectant"
    stage_line = "Preparation stage Reported concentrations refer to the finished product"
    parsed = ParsedCSV(
        filename="supplier-sds.pdf",
        delimiter="pdf_text",
        rows=(("Ingredient CAS Concentration Function",), (ingredient_line,), (stage_line,)),
        source_format="pdf",
        row_pages=(1, 1, 2),
        row_snippets=("Ingredient CAS Concentration Function", ingredient_line, stage_line),
        page_count=2,
    )
    output = interpretation(
        [{
            "source_row": 2,
            "source_name": ingredient_line,
            "interpreted_name": "GLYCERIN",
            "identity_status": "exact_match",
            "source_cas": "56-81-5",
            "source_cas_cell": ingredient_line,
            "source_concentration": ingredient_line,
            "concentration_text": "5%",
            "concentration_value": 5,
            "concentration_unit": "percent",
            "issues": [],
        }],
        mappings=[
            {"source_column_index": 0, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
            {"source_column_index": 0, "mapped_field": "cas_number", "confidence": "high_confidence"},
            {"source_column_index": 0, "mapped_field": "concentration", "confidence": "high_confidence"},
        ],
        data_rows=[2],
        document_assessment={
            "multiple_products_detected": False,
            "reasons": [],
            "sources": [],
        },
    )
    payload = output.model_dump(mode="json")
    payload["ingredients"][0]["preparation_stage"] = "finished_product"
    payload["ingredients"][0]["preparation_stage_sources"] = [{
        "source_row": 3,
        "source_column_index": 0,
        "source_value": stage_line,
    }]
    output = ModelInterpretation.model_validate(payload)

    service = FormulationAgentService(
        load_accepted_store(ROOT),
        load_accepted_ingredient_catalog(ROOT),
        model_runner=lambda *_: output,
    )
    working = _Session(
        parsed=parsed,
        view=AgentSessionView(
            session_id="pdf-stage-test",
            revision=0,
            state=AgentSessionState.PARSING,
            filename=parsed.filename,
            source_format="pdf",
        ),
        touched_at=0,
    )
    service._apply_model_output(working, output)
    session = working.view

    assert session.state.value == "needs_confirmation"
    row = session.interpreted_rows[0]
    assert row.name.value == "GLYCERIN"
    assert row.name.source_value == "GLYCERIN"
    assert row.name.needs_confirmation is False
    assert row.concentration.preparation_stage.value == "finished_product"
    assert row.concentration.preparation_stage.source_references[0].source_row == 3


def test_pdf_with_no_identified_ingredients_stops_with_clear_input_message():
    parsed = ParsedCSV(
        filename="hazards-only.pdf",
        delimiter="pdf_text",
        rows=(("Safety data sheet",), ("Hazard statements only",)),
        source_format="pdf",
        row_pages=(1, 1),
        row_snippets=("Safety data sheet", "Hazard statements only"),
        page_count=1,
    )
    output = ModelInterpretation.model_validate({
        "header_rows": [1],
        "data_rows": [2],
        "column_mappings": [],
        "ingredients": [],
        "formulation_metadata": {
            "formulation_id": {"value": None, "sources": []},
            "formulation_name": {"value": None, "sources": []},
            "product_context": {"value": None, "sources": []},
        },
        "document_assessment": {
            "multiple_products_detected": False,
            "reasons": [],
            "sources": [],
        },
    })
    service = FormulationAgentService(
        load_accepted_store(ROOT),
        load_accepted_ingredient_catalog(ROOT),
        model_runner=lambda *_: output,
    )
    session = service.create(parsed)
    assert session.state.value == "failed"
    assert session.attempts == 1
    assert "No ingredient information" in session.error.message

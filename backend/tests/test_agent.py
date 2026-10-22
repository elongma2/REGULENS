from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
import json

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.app.config import OpenAISettings
from backend.app.main import create_app as build_app
from backend.app.models.agent import AgentAnswer, AgentAnswersRequest, AgentModelRun, AgentPrepareRequest, AgentRowUpdate, ModelInterpretation
from backend.app.models.openai import OpenAIUsage
from backend.app.services.agent_csv import CSVUploadError, parse_csv_upload
from backend.app.services.formulation_agent import (
    AgentExecutionError,
    FormulationAgentService,
    OpenAIFormulationInterpreter,
)
from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.loader import load_accepted_store


ROOT = Path(__file__).resolve().parents[2]


def create_app(*args, **kwargs):
    kwargs.setdefault("settings_loader", lambda: OpenAISettings(None, "gpt-5.6-sol", "gpt-5.6-luna"))
    return build_app(*args, **kwargs)


def interpretation(
    rows: list[dict],
    mappings: list[dict] | None = None,
    *,
    header_rows: list[int] | None = None,
    data_rows: list[int] | None = None,
    formulation_metadata: dict | None = None,
) -> ModelInterpretation:
    """Translate concise test fixtures into the strict semantic-output contract."""
    mappings = mappings or [
        {"source_column_index": 0, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
        {"source_column_index": 1, "mapped_field": "concentration", "confidence": "high_confidence"},
    ]
    mappings = [{key: value for key, value in mapping.items() if key != "source_column"} for mapping in mappings]
    by_field = {mapping["mapped_field"]: mapping["source_column_index"] for mapping in mappings}
    converted = []
    for index, old in enumerate(rows):
        source_row = old["source_row"]
        name_column = by_field.get("ingredient_name", 0)
        concentration_column = by_field.get("concentration", 1)
        cas_column = by_field.get("cas_number", 1)
        concentration_source = old.get("source_concentration")
        uncertainties = []
        if "unit_not_explicit" in old.get("issues", []):
            uncertainties.append("concentration_unit")
        if old.get("identity_status") == "candidate":
            uncertainties.append("ingredient_identity")
        converted.append({
            "row_id": old.get("row_id", f"row-{source_row}-{index}"),
            "source_rows": old.get("source_rows", [source_row]),
            "interpreted_name": old["interpreted_name"],
            "identity_status": old["identity_status"],
            "name_sources": [{
                "source_row": source_row,
                "source_column_index": name_column,
                "source_value": old["source_name"],
            }],
            "proposed_cas": old.get("source_cas"),
            "cas_sources": ([{
                "source_row": source_row,
                "source_column_index": cas_column,
                "source_value": old["source_cas"],
            }] if old.get("source_cas") else []),
            "concentration_value": old.get("concentration_value"),
            "concentration_unit": old.get("concentration_unit"),
            "concentration_value_sources": ([{
                "source_row": source_row,
                "source_column_index": concentration_column,
                "source_value": concentration_source,
            }] if concentration_source is not None else []),
            "concentration_unit_sources": [],
            "basis": None,
            "basis_sources": [],
            "preparation_stage": None,
            "preparation_stage_sources": [],
            "regulated_functions": old.get("regulated_functions", []),
            "regulated_function_sources": old.get("regulated_function_sources", []),
            "uncertainties": uncertainties,
            "issues": old.get("issues", []),
        })
    null_metadata = {"value": None, "sources": []}
    return ModelInterpretation.model_validate({
        "header_rows": header_rows or [1],
        "data_rows": data_rows or [row["source_row"] for row in rows],
        "column_mappings": mappings,
        "ingredients": converted,
        "formulation_metadata": formulation_metadata or {
            "formulation_id": null_metadata,
            "formulation_name": null_metadata,
            "product_context": null_metadata,
        },
    })


def clean_runner(parsed, store, catalogue, model):
    return interpretation([
        {"source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE", "identity_status": "exact_match", "identity_catalogue_id": None, "source_cas": None, "source_concentration": "5%", "concentration_value": 5, "concentration_unit": "percent", "issues": []},
        {"source_row": 3, "source_name": "GLYCERIN", "interpreted_name": "GLYCERIN", "identity_status": "exact_match", "identity_catalogue_id": None, "source_cas": None, "source_concentration": "4%", "concentration_value": 4, "concentration_unit": "percent", "issues": []},
        {"source_row": 4, "source_name": "Tosylchloramide sodium", "interpreted_name": "Tosylchloramide sodium", "identity_status": "exact_match", "identity_catalogue_id": None, "source_cas": None, "source_concentration": "0.21%", "concentration_value": 0.21, "concentration_unit": "percent", "issues": []},
    ])


@pytest.fixture(scope="module")
def store():
    return load_accepted_store(ROOT)


@pytest.fixture(scope="module")
def catalogue():
    return load_accepted_ingredient_catalog(ROOT)


@pytest.fixture()
def client(store, catalogue):
    factory = lambda loaded_store, loaded_catalogue: FormulationAgentService(
        loaded_store, loaded_catalogue, model_runner=clean_runner
    )
    with TestClient(create_app(lambda: store, lambda: catalogue, factory)) as test_client:
        yield test_client


def test_csv_parser_preserves_source_cells_and_supports_bom():
    parsed = parse_csv_upload("formula.csv", "INCI,Concentration\nNIACINAMIDE,5%\n".encode("utf-8-sig"))
    assert parsed.rows[1] == ("NIACINAMIDE", "5%")
    assert parsed.filename == "formula.csv"
    assert parsed.delimiter == ","


def test_csv_parser_rejects_invalid_files():
    with pytest.raises(CSVUploadError, match="Supported formulation files"):
        parse_csv_upload("formula.docx", b"a,b")
    with pytest.raises(CSVUploadError, match="empty"):
        parse_csv_upload("formula.csv", b"")


def _xlsx_upload(rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_formulation_parser_accepts_xlsx_and_json_grids():
    xlsx = parse_csv_upload(
        "formula.xlsx",
        _xlsx_upload([["INCI", "Concentration"], ["NIACINAMIDE", "5%"]]),
    )
    assert xlsx.rows == (("INCI", "Concentration"), ("NIACINAMIDE", "5%"))
    assert xlsx.filename == "formula.xlsx"

    json_grid = parse_csv_upload(
        "formula.json",
        json.dumps({"rows": [["INCI", "Concentration"], ["GLYCERIN", "4%"]]}).encode(),
    )
    assert json_grid.rows[1] == ("GLYCERIN", "4%")


@pytest.mark.parametrize(
    ("filename", "content"),
    [("broken.xlsx", b"not an xlsx"), ("broken.xls", b"not an xls"), ("broken.pdf", b"not a pdf")],
)
def test_binary_formulation_parser_returns_bounded_errors(filename, content):
    with pytest.raises(CSVUploadError, match="could not be read"):
        parse_csv_upload(filename, content)


def test_agent_route_accepts_browser_xlsx_content_type(client):
    response = client.post(
        "/agent/formulations",
        files={"file": (
            "clean.xlsx",
            _xlsx_upload([
                ["INCI", "Concentration"],
                ["NIACINAMIDE", "5%"],
                ["GLYCERIN", "4%"],
                ["Tosylchloramide sodium", "0.21%"],
            ]),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "clean.xlsx"


def test_agent_upload_confirmation_prepare_and_existing_screening(client):
    response = client.post(
        "/agent/formulations",
        files={"file": ("clean.csv", b"INCI,Concentration\nNIACINAMIDE,5%\nGLYCERIN,4%\nTosylchloramide sodium,0.21%\n", "text/csv")},
    )
    assert response.status_code == 201
    session = response.json()
    assert session["state"] == "needs_confirmation"
    assert [row["source_row"] for row in session["interpreted_rows"]] == [2, 3, 4]
    assert {question["question_id"] for question in session["questions"]} == {
        "formulation:product_context",
        "global:preparation_stage",
    }
    assert session["interpreted_rows"][0]["name"]["source_value"] == "NIACINAMIDE"
    identity_evidence = session["interpreted_rows"][0]["catalogue_identity"]
    assert identity_evidence["canonical_name"] == "NIACINAMIDE"
    assert identity_evidence["source_entries"] == [17380]
    assert identity_evidence["source_pages"] == [516]
    assert identity_evidence["raw_record_ids"] == ["raw-eu-2025-1175-entry-17380"]

    answered = client.post(
        f'/agent/formulations/{session["session_id"]}/answers',
        json={"revision": session["revision"], "answers": [
            {"question_id": "formulation:product_context", "option_id": "not_supplied"},
            {"question_id": "global:preparation_stage", "option_id": "finished_product"},
        ]},
    )
    assert answered.status_code == 200
    updated = answered.json()
    assert updated["questions"] == []
    assert updated["interpreted_rows"][0]["concentration"]["preparation_stage"]["interpretation_method"] == "user_confirmed_global_stage"

    prepared = client.post(
        f'/agent/formulations/{session["session_id"]}/prepare',
        json={"revision": updated["revision"], "formulation_id": "CSV-001", "formulation_name": "Imported demo", "product_context": None},
    )
    assert prepared.status_code == 200
    canonical = prepared.json()["formulation"]
    assert canonical["ingredients"][0]["concentration"] == {
        "value": 5.0, "unit": "percent", "basis": None, "preparation_stage": "finished_product"
    }
    screened = client.post("/screen-formulation", json=canonical)
    assert screened.status_code == 200
    assert screened.json()["summary"]["ingredients_submitted"] == 3


def test_prepare_is_blocked_before_confirmation_and_stale_answers_conflict(client):
    session = client.post(
        "/agent/formulations",
        files={"file": ("clean.csv", b"INCI,Concentration\nNIACINAMIDE,5%\nGLYCERIN,4%\nTosylchloramide sodium,0.21%\n", "text/csv")},
    ).json()
    blocked = client.post(
        f'/agent/formulations/{session["session_id"]}/prepare',
        json={"revision": session["revision"], "formulation_id": None, "formulation_name": None, "product_context": None},
    )
    assert blocked.status_code == 409
    first = client.post(
        f'/agent/formulations/{session["session_id"]}/answers',
        json={"revision": session["revision"], "answers": [
            {"question_id": "formulation:product_context", "option_id": "not_supplied"},
            {"question_id": "global:preparation_stage", "option_id": "finished_product"},
        ]},
    )
    assert first.status_code == 200
    stale = client.post(
        f'/agent/formulations/{session["session_id"]}/answers',
        json={"revision": session["revision"], "answers": [{"question_id": "global:preparation_stage", "option_id": "ready_for_use"}]},
    )
    assert stale.status_code == 409


def test_qs_and_missing_unit_create_targeted_questions(store, catalogue):
    def messy_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([
            {"source_row": 2, "source_name": "Niacinamide", "interpreted_name": "NIACINAMIDE", "identity_status": "exact_match", "identity_catalogue_id": None, "source_cas": None, "source_concentration": "5", "concentration_value": 5, "concentration_unit": "percent", "issues": ["unit_not_explicit"]},
            {"source_row": 3, "source_name": "Perfume", "interpreted_name": "Perfume", "identity_status": "unresolved", "identity_catalogue_id": None, "source_cas": None, "source_concentration": "QS", "concentration_value": None, "concentration_unit": None, "issues": ["non_numeric_concentration"]},
        ])
    service = FormulationAgentService(store, catalogue, model_runner=messy_runner)
    session = service.create(parse_csv_upload("messy.csv", b"INCI,Concentration\nNiacinamide,5\nPerfume,QS\n"))
    assert {question.question_type for question in session.questions} == {
        "unit", "preparation_stage", "product_context", "non_numeric_concentration",
    }
    assert session.interpreted_rows[1].concentration is None
    unit_question = next(question for question in session.questions if question.question_type == "unit")
    assert unit_question.row_id == session.interpreted_rows[0].row_id
    assert unit_question.target_field == "concentration.unit"
    assert unit_question.uncertainty_code == "missing_concentration_unit"
    assert unit_question.prompt == 'The CSV gives concentration "5" but no unit.'
    nonnumeric = next(question for question in session.questions if question.question_type == "non_numeric_concentration")
    assert nonnumeric.row_id == session.interpreted_rows[1].row_id
    assert nonnumeric.prompt == '"QS" cannot be converted safely to a numeric concentration.'


def test_direct_unit_edit_resolves_only_that_row_question(store, catalogue):
    def runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([
            {"source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE", "identity_status": "exact_match", "source_cas": None, "source_concentration": "5", "concentration_value": 5, "concentration_unit": None, "issues": ["unit_not_explicit"]},
            {"source_row": 3, "source_name": "GLYCERIN", "interpreted_name": "GLYCERIN", "identity_status": "exact_match", "source_cas": None, "source_concentration": "4", "concentration_value": 4, "concentration_unit": None, "issues": ["unit_not_explicit"]},
        ])

    service = FormulationAgentService(store, catalogue, model_runner=runner)
    session = service.create(parse_csv_upload("units.csv", b"INCI,Amount\nNIACINAMIDE,5\nGLYCERIN,4\n"))
    first = session.interpreted_rows[0]
    updated = service.apply_answers(session.session_id, AgentAnswersRequest(
        revision=session.revision,
        row_updates=[AgentRowUpdate(
            row_id=first.row_id,
            concentration_value=5,
            concentration_unit="percent",
            concentration_basis=None,
            preparation_stage=None,
        )],
    ))

    unit_questions = [question for question in updated.questions if question.question_type == "unit"]
    assert len(unit_questions) == 1
    assert unit_questions[0].source_row == 3
    assert not any(item.uncertainty_code == "missing_concentration_unit" for item in updated.interpreted_rows[0].unresolved_fields)


def test_malformed_imported_cas_blocks_until_removed(store, catalogue):
    def runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation(
            [{"source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE", "identity_status": "exact_match", "source_cas": "123-45-6", "source_concentration": None, "concentration_value": None, "concentration_unit": None, "issues": []}],
            mappings=[
                {"source_column_index": 0, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
                {"source_column_index": 1, "mapped_field": "cas_number", "confidence": "high_confidence"},
            ],
        )

    service = FormulationAgentService(store, catalogue, model_runner=runner)
    session = service.create(parse_csv_upload("bad-cas.csv", b"INCI,CAS\nNIACINAMIDE,123-45-6\n"))
    question = next(item for item in session.questions if item.question_type == "cas_number")
    assert question.row_id == session.interpreted_rows[0].row_id

    updated = service.apply_answers(session.session_id, AgentAnswersRequest(
        revision=session.revision,
        answers=[AgentAnswer(question_id=question.question_id, option_id="remove_invalid_cas")],
    ))
    assert updated.interpreted_rows[0].cas_number.value is None
    assert all(item.question_type != "cas_number" for item in updated.questions)


def test_non_exact_identity_requires_confirmation(store, catalogue):
    def candidate_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([
            {"source_row": 2, "source_name": "Tosyl chl Na", "interpreted_name": "Tosylchloramide sodium", "identity_status": "candidate", "identity_catalogue_id": None, "source_cas": None, "source_concentration": None, "concentration_value": None, "concentration_unit": None, "issues": []},
        ])
    session = FormulationAgentService(store, catalogue, model_runner=candidate_runner).create(
        parse_csv_upload("candidate.csv", b"INCI,Concentration\nTosyl chl Na,\n")
    )
    assert session.interpreted_rows[0].name.source_value == "Tosyl chl Na"
    assert session.interpreted_rows[0].name.needs_confirmation is True
    assert any(question.question_type == "identity" for question in session.questions)


def test_unchanged_unmatched_identity_has_no_fake_recommendation(store, catalogue):
    def unresolved_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([{
            "source_row": 2, "source_name": "Mystery Extract", "interpreted_name": "Mystery Extract",
            "identity_status": "candidate", "source_cas": None, "source_concentration": None,
            "concentration_value": None, "concentration_unit": None, "issues": [],
        }])

    session = FormulationAgentService(store, catalogue, model_runner=unresolved_runner).create(
        parse_csv_upload("mystery.csv", b"INCI,Amount\nMystery Extract,\n")
    )
    question = next(question for question in session.questions if question.question_type == "identity")
    assert question.prompt == "Regulens could not find a source-backed identity match."
    assert [option.option_id for option in question.options] == ["keep_source"]
    assert all("Confirm Mystery Extract" not in option.label for option in question.options)


def test_direct_exact_identity_edit_resolves_identity_question(store, catalogue):
    def candidate_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([{
            "source_row": 2, "source_name": "Glycerine", "interpreted_name": "Glycerine",
            "identity_status": "candidate", "source_cas": None, "source_concentration": None,
            "concentration_value": None, "concentration_unit": None, "issues": [],
        }])

    service = FormulationAgentService(store, catalogue, model_runner=candidate_runner)
    session = service.create(parse_csv_upload("identity.csv", b"INCI,Amount\nGlycerine,\n"))
    row = session.interpreted_rows[0]
    assert any(question.question_type == "identity" for question in session.questions)

    updated = service.apply_answers(session.session_id, AgentAnswersRequest(
        revision=session.revision,
        row_updates=[AgentRowUpdate(row_id=row.row_id, name="GLYCERIN")],
    ))

    assert updated.interpreted_rows[0].name.value == "GLYCERIN"
    assert updated.interpreted_rows[0].identity_status == "confirmed"
    assert not any(question.question_type == "identity" for question in updated.questions)


def test_direct_unmatched_identity_edit_can_be_explicitly_confirmed(store, catalogue):
    def unresolved_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([{
            "source_row": 2, "source_name": "Wrong supplier name", "interpreted_name": "Wrong supplier name",
            "identity_status": "unresolved", "source_cas": None, "source_concentration": None,
            "concentration_value": None, "concentration_unit": None, "issues": [],
        }])

    service = FormulationAgentService(store, catalogue, model_runner=unresolved_runner)
    session = service.create(parse_csv_upload("identity.csv", b"INCI,Amount\nWrong supplier name,\n"))
    row = session.interpreted_rows[0]
    edited = service.apply_answers(session.session_id, AgentAnswersRequest(
        revision=session.revision,
        row_updates=[AgentRowUpdate(row_id=row.row_id, name="Corrected supplier identity")],
    ))

    question = next(question for question in edited.questions if question.question_type == "identity")
    assert [(option.option_id, option.value) for option in question.options] == [
        ("confirm_entered", "Corrected supplier identity"),
        ("keep_source", "Wrong supplier name"),
    ]
    assert question.prompt == "Confirm the entered ingredient name or return to the source value."

    confirmed = service.apply_answers(session.session_id, AgentAnswersRequest(
        revision=edited.revision,
        answers=[AgentAnswer(question_id=question.question_id, option_id="confirm_entered")],
    ))
    confirmed_row = confirmed.interpreted_rows[0]
    assert confirmed_row.name.value == "Corrected supplier identity"
    assert confirmed_row.name.confirmed_by_user is True
    assert confirmed_row.name.interpretation_method == "user_confirmed_entered_identity"
    assert confirmed_row.identity_status == "unresolved"
    assert not any(item.question_type == "identity" for item in confirmed.questions)


def test_optional_source_metadata_is_preserved_and_inci_is_the_identity_field(store, catalogue):
    def metadata_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation(
            [{
                "source_row": 2,
                "source_name": "Niacinamide",
                "interpreted_name": "NIACINAMIDE",
                "identity_status": "exact_match",
                "identity_catalogue_id": None,
                "source_cas": None,
                "source_concentration": "5%",
                "concentration_value": 5,
                "concentration_unit": "percent",
                "issues": [],
            }],
            mappings=[
                {"source_column": "RM Name", "source_column_index": 0, "mapped_field": "raw_material_name", "confidence": "high_confidence"},
                {"source_column": "INCI", "source_column_index": 1, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
                {"source_column": "Dosage", "source_column_index": 2, "mapped_field": "concentration", "confidence": "high_confidence"},
            ],
        )

    session = FormulationAgentService(store, catalogue, model_runner=metadata_runner).create(
        parse_csv_upload("metadata.csv", b"RM Name,INCI,Dosage\nVitamin B3 Active,Niacinamide,5%\n")
    )
    row = session.interpreted_rows[0]
    assert row.name.source_column == "INCI"
    assert row.name.source_value == "Niacinamide"
    assert row.name.value == "NIACINAMIDE"
    assert [(item.source_column, item.source_value, item.mapped_as) for item in row.source_metadata] == [
        ("RM Name", "Vitamin B3 Active", "raw_material_name")
    ]
    assert all(item.source_column != "Notes" for item in row.source_metadata)


def test_product_context_exact_match_and_ambiguous_value_are_kept_distinct(store, catalogue):
    def context_runner(source_context: str):
        def run(parsed, accepted_store, accepted_catalogue, model):
            return interpretation(
                [{
                    "source_row": 2,
                    "source_name": "NIACINAMIDE",
                    "interpreted_name": "NIACINAMIDE",
                    "identity_status": "exact_match",
                    "identity_catalogue_id": None,
                    "source_cas": None,
                    "source_concentration": None,
                    "concentration_value": None,
                    "concentration_unit": None,
                    "issues": [],
                }],
                mappings=[
                    {"source_column": "Ingredient", "source_column_index": 0, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
                    {"source_column": "Product Type", "source_column_index": 1, "mapped_field": "product_context", "confidence": "high_confidence"},
                ],
                formulation_metadata={
                    "formulation_id": {"value": None, "sources": []},
                    "formulation_name": {"value": None, "sources": []},
                    "product_context": {
                        "value": source_context,
                        "sources": [{"source_row": 2, "source_column_index": 1, "source_value": source_context}],
                    },
                },
            )
        return run

    exact = FormulationAgentService(store, catalogue, model_runner=context_runner("Toothpaste")).create(
        parse_csv_upload("exact-context.csv", b"Ingredient,Product Type\nNIACINAMIDE,Toothpaste\n")
    )
    assert exact.product_context.value == "Toothpaste"
    assert exact.product_context.interpretation_method == "exact_product_context_match"
    assert not any(question.question_type == "product_context" for question in exact.questions)

    ambiguous = FormulationAgentService(store, catalogue, model_runner=context_runner("rinse product")).create(
        parse_csv_upload("ambiguous-context.csv", b"Ingredient,Product Type\nNIACINAMIDE,rinse product\n")
    )
    assert ambiguous.product_context.value is None
    assert ambiguous.product_context.source_value == "rinse product"
    assert ambiguous.product_context.needs_confirmation is True
    assert any(question.question_type == "product_context" for question in ambiguous.questions)


def test_preamble_product_context_is_semantic_and_omitted_declared_rows_fail(store, catalogue):
    def partial_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([{
                "source_row": 4,
                "source_name": "NIACINAMIDE",
                "interpreted_name": "NIACINAMIDE",
                "identity_status": "exact_match",
                "identity_catalogue_id": None,
                "source_cas": None,
                "source_concentration": "5%",
                "concentration_value": 5,
                "concentration_unit": "percent",
                "issues": [],
            }], mappings=[
                {"source_column_index": 0, "mapped_field": "metadata", "confidence": "high_confidence"},
                {"source_column_index": 1, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
                {"source_column_index": 2, "mapped_field": "concentration", "confidence": "high_confidence"},
            ], header_rows=[3], data_rows=[4, 5], formulation_metadata={
                "formulation_id": {"value": None, "sources": []},
                "formulation_name": {"value": None, "sources": []},
                "product_context": {
                    "value": "Toothpaste",
                    "sources": [{"source_row": 1, "source_column_index": 2, "source_value": "Toothpaste"}],
                },
            })

    parsed = parse_csv_upload(
        "metadata-preamble.csv",
        b"Product Type,,Toothpaste\n\nSeq,INCI,Dose\n1,NIACINAMIDE,5%\n2,AQUA,balance\n",
    )
    session = FormulationAgentService(store, catalogue, model_runner=partial_runner).create(parsed)

    assert session.state == "failed"
    assert session.error.code == "agent_invalid_source_reference"
    assert session.filename == "metadata-preamble.csv"


def test_missing_product_context_requires_an_explicit_choice_and_enters_canonical_request(store, catalogue):
    def identity_only_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([{
            "source_row": 2,
            "source_name": "NIACINAMIDE",
            "interpreted_name": "NIACINAMIDE",
            "identity_status": "exact_match",
            "identity_catalogue_id": None,
            "source_cas": None,
            "source_concentration": None,
            "concentration_value": None,
            "concentration_unit": None,
            "issues": [],
        }], mappings=[
            {"source_column": "Ingredient", "source_column_index": 0, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
        ])

    service = FormulationAgentService(store, catalogue, model_runner=identity_only_runner)
    session = service.create(parse_csv_upload("missing-context.csv", b"Ingredient\nNIACINAMIDE\n"))
    question = next(item for item in session.questions if item.question_type == "product_context")
    selected = next(option for option in question.options if option.value == "Toothpaste")
    updated = service.apply_answers(session.session_id, AgentAnswersRequest(
        revision=session.revision,
        answers=[AgentAnswer(question_id=question.question_id, option_id=selected.option_id)],
    ))
    assert updated.product_context.value == "Toothpaste"
    prepared = service.prepare(session.session_id, AgentPrepareRequest(
        revision=updated.revision,
        product_context="Toothpaste",
    ))
    assert prepared.formulation.product_context == "Toothpaste"


def test_changed_model_source_copy_fails_exact_reference_validation(store, catalogue):
    def changed_copy_runner(parsed, accepted_store, accepted_catalogue, model):
        return interpretation([
            {"source_row": 2, "source_name": "Niacinamide ", "interpreted_name": "Niacinamide", "identity_status": "exact_match", "identity_catalogue_id": None, "source_cas": None, "source_concentration": None, "concentration_value": None, "concentration_unit": None, "issues": []},
        ])

    session = FormulationAgentService(store, catalogue, model_runner=changed_copy_runner).create(
        parse_csv_upload("source-copy.csv", b"INCI,Concentration\nNiacinamide,\n")
    )
    assert session.state == "failed"
    assert session.error.code == "agent_invalid_source_reference"


def test_logical_ingredient_can_combine_exact_cells_from_multiple_rows(store, catalogue):
    def multirow_runner(parsed, accepted_store, accepted_catalogue, model):
        return ModelInterpretation.model_validate({
            "header_rows": [3],
            "data_rows": [4, 5],
            "column_mappings": [
                {"source_column_index": 0, "mapped_field": "concentration", "confidence": "high_confidence"},
                {"source_column_index": 1, "mapped_field": "ingredient_name", "confidence": "high_confidence"},
                {"source_column_index": 2, "mapped_field": "raw_material_name", "confidence": "high_confidence"},
            ],
            "ingredients": [{
                "row_id": "b3-active",
                "source_rows": [4, 5],
                "interpreted_name": "NIACINAMIDE",
                "identity_status": "exact_match",
                "name_sources": [{"source_row": 5, "source_column_index": 1, "source_value": "NIACINAMIDE"}],
                "proposed_cas": None,
                "cas_sources": [],
                "concentration_value": 5,
                "concentration_unit": None,
                "concentration_value_sources": [{"source_row": 4, "source_column_index": 0, "source_value": "5"}],
                "concentration_unit_sources": [],
                "basis": None,
                "basis_sources": [],
                "preparation_stage": None,
                "preparation_stage_sources": [],
                "regulated_functions": [],
                "regulated_function_sources": [],
                "uncertainties": ["concentration_unit"],
                "issues": [],
            }],
            "formulation_metadata": {
                "formulation_id": {"value": None, "sources": []},
                "formulation_name": {"value": "Night Serum", "sources": [{"source_row": 1, "source_column_index": 0, "source_value": "Night Serum"}]},
                "product_context": {"value": None, "sources": []},
            },
        })

    parsed = parse_csv_upload(
        "multirow.csv",
        b"Night Serum,,\n,,\nAmount,INCI,RM Name\n5,,B3 Active\n,NIACINAMIDE,B3 Active\n",
    )
    session = FormulationAgentService(store, catalogue, model_runner=multirow_runner).create(parsed)
    assert session.state == "needs_confirmation"
    assert session.interpreted_rows[0].source_rows == [4, 5]
    assert session.interpreted_rows[0].name.source_row == 5
    assert session.interpreted_rows[0].concentration.value.source_row == 4
    assert session.formulation_name.value == "Night Serum"


def test_semantic_reference_failure_gets_one_bounded_repair(store, catalogue):
    valid = interpretation([{
        "source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE",
        "identity_status": "exact_match", "source_cas": None, "source_concentration": "5%",
        "concentration_value": 5, "concentration_unit": "percent", "issues": [],
    }])
    invalid = valid.model_copy(deep=True)
    invalid.ingredients[0].name_sources[0].source_value = "CHANGED"

    class RepairingInterpreter(OpenAIFormulationInterpreter):
        def __init__(self):
            super().__init__(api_key="test")
            self.repairs = 0

        def __call__(self, *args):
            return invalid

        def repair(self, *args):
            self.repairs += 1
            return AgentModelRun(
                interpretation=valid,
                usage=OpenAIUsage(configured_model="gpt-5.6-sol", actual_model="gpt-5.6-sol", request_rounds=1),
            )

    interpreter = RepairingInterpreter()
    session = FormulationAgentService(store, catalogue, model_runner=interpreter).create(
        parse_csv_upload("repair.csv", b"INCI,Concentration\nNIACINAMIDE,5%\n")
    )
    assert interpreter.repairs == 1
    assert session.state == "needs_confirmation"
    assert session.interpreted_rows[0].name.value == "NIACINAMIDE"


def test_source_reference_failure_after_repair_retries_full_interpretation(store, catalogue):
    valid = interpretation([{
        "source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE",
        "identity_status": "exact_match", "source_cas": None, "source_concentration": "5%",
        "concentration_value": 5, "concentration_unit": "percent", "issues": [],
    }])
    invalid = valid.model_copy(deep=True)
    invalid.ingredients[0].name_sources[0].source_value = "CHANGED"

    class RetryAfterRepairInterpreter(OpenAIFormulationInterpreter):
        def __init__(self):
            super().__init__(api_key="test")
            self.calls = 0

        def __call__(self, *args):
            self.calls += 1
            output = invalid if self.calls == 1 else valid
            return AgentModelRun(
                interpretation=output,
                usage=OpenAIUsage(configured_model="gpt-5.6-sol", input_tokens=10, total_tokens=10),
            )

        def repair(self, *args):
            return AgentModelRun(
                interpretation=invalid,
                usage=OpenAIUsage(configured_model="gpt-5.6-sol", input_tokens=5, total_tokens=5),
            )

    interpreter = RetryAfterRepairInterpreter()
    session = FormulationAgentService(
        store, catalogue, model_runner=interpreter, sleep=lambda _: None,
    ).create(parse_csv_upload("repair-retry.csv", b"INCI,Concentration\nNIACINAMIDE,5%\n"))

    assert session.state == "needs_confirmation"
    assert session.attempts == 2
    assert session.successful_attempt == 2
    assert session.attempt_diagnostics[0].failure_category == "source_reference"
    assert session.total_usage.input_tokens == 25


def test_model_failure_retains_recoverable_session(store, catalogue):
    def failed_runner(*args):
        raise AgentExecutionError("agent_model_unavailable", "Model unavailable")
    session = FormulationAgentService(store, catalogue, model_runner=failed_runner).create(
        parse_csv_upload("clean.csv", b"INCI,Concentration\nNIACINAMIDE,5%\n")
    )
    assert session.state == "failed"
    assert session.error.recoverable is True
    assert session.filename == "clean.csv"
    assert session.attempts == 1


def test_transient_schema_failure_retries_and_aggregates_usage(store, catalogue):
    valid = interpretation([{
        "source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE",
        "identity_status": "exact_match", "source_cas": None, "source_concentration": "5%",
        "concentration_value": 5, "concentration_unit": "percent", "issues": [],
    }])

    class FlakyRunner:
        calls = 0

        def __call__(self, *args):
            self.calls += 1
            usage = OpenAIUsage(
                configured_model="gpt-5.6-sol", actual_model="gpt-5.6-sol",
                input_tokens=100 * self.calls, output_tokens=10 * self.calls,
                total_tokens=110 * self.calls, request_rounds=1,
                response_ids=[f"resp-{self.calls}"],
            )
            if self.calls == 1:
                raise AgentExecutionError(
                    "agent_invalid_structured_output", "invalid schema", transient=True,
                    failure_category="structured_output", usage=usage,
                )
            return AgentModelRun(interpretation=valid, usage=usage)

    runner = FlakyRunner()
    delays = []
    session = FormulationAgentService(
        store, catalogue, model_runner=runner, sleep=delays.append,
    ).create(parse_csv_upload("retry.csv", b"INCI,Concentration\nNIACINAMIDE,5%\n"))

    assert session.state == "needs_confirmation"
    assert session.attempts == 2
    assert session.successful_attempt == 2
    assert [item.status for item in session.attempt_diagnostics] == ["failure", "success"]
    assert session.total_usage.input_tokens == 300
    assert session.total_usage.output_tokens == 30
    assert session.total_usage.response_ids == ["resp-1", "resp-2"]
    assert session.usage == session.total_usage
    assert delays == [0.5]


def test_transient_timeout_retries_transparently(store, catalogue):
    valid = interpretation([{
        "source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE",
        "identity_status": "exact_match", "source_cas": None, "source_concentration": None,
        "concentration_value": None, "concentration_unit": None, "issues": [],
    }])
    calls = 0

    def runner(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AgentExecutionError(
                "agent_model_unavailable", "timeout", transient=True,
                failure_category="timeout", usage=OpenAIUsage(configured_model="gpt-5.6-sol"),
            )
        return valid

    session = FormulationAgentService(store, catalogue, model_runner=runner, sleep=lambda _: None).create(
        parse_csv_upload("timeout.csv", b"INCI,Concentration\nNIACINAMIDE,\n")
    )
    assert session.state == "needs_confirmation"
    assert session.attempts == 2
    assert session.attempt_diagnostics[0].failure_category == "timeout"
    assert all(item.message != "Interpretation could not be completed" for item in session.activity)


def test_three_transient_failures_then_manual_retry_reuses_session_history(store, catalogue):
    valid = interpretation([{
        "source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE",
        "identity_status": "exact_match", "source_cas": None, "source_concentration": None,
        "concentration_value": None, "concentration_unit": None, "issues": [],
    }])
    parsed_objects = []

    def runner(parsed, *args):
        parsed_objects.append(parsed)
        attempt = len(parsed_objects)
        usage = OpenAIUsage(configured_model="gpt-5.6-sol", input_tokens=10, total_tokens=10)
        if attempt <= 3:
            raise AgentExecutionError(
                "agent_model_unavailable", "temporary", transient=True,
                failure_category="temporary_api", usage=usage,
            )
        return AgentModelRun(interpretation=valid, usage=usage)

    service = FormulationAgentService(store, catalogue, model_runner=runner, sleep=lambda _: None)
    failed = service.create(parse_csv_upload("retained.csv", b"INCI,Concentration\nNIACINAMIDE,\n"))
    assert failed.state == "failed"
    assert failed.attempts == 3
    assert failed.error.recoverable is True
    assert failed.error.message == "Regulens tried to interpret this formulation but could not produce a reliable structured result. Your uploaded file has been preserved."

    recovered = service.retry(failed.session_id)
    assert recovered.state == "needs_confirmation"
    assert recovered.attempts == 4
    assert recovered.successful_attempt == 4
    assert len({id(item) for item in parsed_objects}) == 1
    assert recovered.total_usage.input_tokens == 40


def test_successful_ambiguity_is_not_retried(store, catalogue):
    ambiguous = interpretation([{
        "source_row": 2, "source_name": "Mystery Extract", "interpreted_name": "Mystery Extract",
        "identity_status": "candidate", "source_cas": None, "source_concentration": None,
        "concentration_value": None, "concentration_unit": None, "issues": [],
    }])
    calls = 0

    def runner(*args):
        nonlocal calls
        calls += 1
        return ambiguous

    session = FormulationAgentService(store, catalogue, model_runner=runner, sleep=lambda _: None).create(
        parse_csv_upload("ambiguous.csv", b"INCI,Concentration\nMystery Extract,\n")
    )
    assert session.state == "needs_confirmation"
    assert calls == 1
    assert session.attempts == 1
    assert any(question.question_type == "identity" for question in session.questions)


def test_malformed_upload_never_reaches_interpreter(store, catalogue):
    calls = 0

    def runner(*args):
        nonlocal calls
        calls += 1
        raise AssertionError("model must not run")

    service = FormulationAgentService(store, catalogue, model_runner=runner, sleep=lambda _: None)
    app = create_app(formulation_agent_factory=lambda *_: service)
    with TestClient(app) as client:
        response = client.post("/agent/formulations", files={"file": ("bad.csv", b"\xff\xfe\x00", "text/csv")})
    assert response.status_code == 422
    assert calls == 0


def test_openai_tools_are_strict_read_only_and_never_screen(store, catalogue):
    tool_names = {tool["name"] for tool in OpenAIFormulationInterpreter.tools()}
    assert tool_names == {
        "search_ingredient_catalogue",
        "search_singapore_regulatory_records",
        "search_acd_regulatory_records",
        "validate_formulation",
    }
    assert all(tool["strict"] is True for tool in OpenAIFormulationInterpreter.tools())
    before = store.rules_by_id["acd-iii-14"].copy()
    result = OpenAIFormulationInterpreter._run_tool("search_acd_regulatory_records", {"query": "hydroquinone"}, store, catalogue)
    assert result["results"]
    assert store.rules_by_id["acd-iii-14"] == before


def test_openai_interpretation_schema_requires_every_declared_property():
    schema = ModelInterpretation.model_json_schema()

    def assert_strict_objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert set(node["required"]) == set(node["properties"])
                assert node.get("additionalProperties") is False
            for value in node.values():
                assert_strict_objects(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict_objects(value)

    assert_strict_objects(schema)


def test_responses_api_is_stateless_bounded_and_sends_parsed_cells_only(monkeypatch, store, catalogue):
    calls = []
    client_kwargs = {}
    tool_call = SimpleNamespace(
        type="function_call",
        name="search_ingredient_catalogue",
        arguments='{"query":"NIACINAMIDE"}',
        call_id="call-1",
        model_dump=lambda **kwargs: {
            "type": "function_call", "name": "search_ingredient_catalogue",
            "arguments": '{"query":"NIACINAMIDE"}', "call_id": "call-1", "status": "completed",
        },
    )
    final_output = interpretation([
        {"source_row": 2, "source_name": "NIACINAMIDE", "interpreted_name": "NIACINAMIDE", "identity_status": "exact_match", "identity_catalogue_id": "eu-id", "source_cas": None, "source_concentration": "5%", "concentration_value": 5, "concentration_unit": "percent", "issues": []},
    ]).model_dump_json()

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(id="resp-tool", model="gpt-5.6-sol", usage=SimpleNamespace(input_tokens=20, output_tokens=5, total_tokens=25), output=[tool_call], output_text="")
            return SimpleNamespace(id="resp-final", model="gpt-5.6-sol", usage=SimpleNamespace(input_tokens=30, output_tokens=10, total_tokens=40), output=[], output_text=final_output)

    def fake_openai(**kwargs):
        client_kwargs.update(kwargs)
        return SimpleNamespace(responses=FakeResponses())

    monkeypatch.setattr(
        "backend.app.services.formulation_agent.OpenAI",
        fake_openai,
    )
    parsed = parse_csv_upload("private-name.csv", b"INCI,Concentration\nNIACINAMIDE,5%\n")
    output = OpenAIFormulationInterpreter(api_key="test")(parsed, store, catalogue, "gpt-5.6-sol")
    assert output.interpretation.ingredients[0].name_sources[0].source_value == "NIACINAMIDE"
    assert all(call["store"] is False for call in calls)
    assert all(call["max_tool_calls"] <= 12 for call in calls)
    first_payload = json.dumps(calls[0]["input"])
    assert "private-name.csv" not in first_payload
    assert str(ROOT) not in first_payload
    assert "source_text" not in first_payload
    assert any(item.get("type") == "function_call_output" for item in calls[1]["input"])
    continued_call = next(item for item in calls[1]["input"] if item.get("type") == "function_call")
    assert "status" not in continued_call
    assert client_kwargs["max_retries"] == 0
    assert client_kwargs["timeout"] == 180
    assert output.usage.response_ids == ["resp-tool", "resp-final"]
    assert output.usage.input_tokens == 50


def test_tool_round_limit_forces_a_final_structured_response_without_more_tools(monkeypatch, store, catalogue):
    calls = []
    final_output = interpretation([{
        "source_row": 2,
        "source_name": "NIACINAMIDE",
        "interpreted_name": "NIACINAMIDE",
        "identity_status": "exact_match",
        "identity_catalogue_id": None,
        "source_cas": None,
        "source_concentration": "5%",
        "concentration_value": 5,
        "concentration_unit": "percent",
        "issues": [],
    }]).model_dump_json()

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("tools") == []:
                return SimpleNamespace(output=[], output_text=final_output)
            call_number = len(calls)
            tool_call = SimpleNamespace(
                type="function_call",
                name="search_ingredient_catalogue",
                arguments='{"query":"NIACINAMIDE"}',
                call_id=f"call-{call_number}",
                model_dump=lambda **dump_kwargs: {
                    "type": "function_call",
                    "name": "search_ingredient_catalogue",
                    "arguments": '{"query":"NIACINAMIDE"}',
                    "call_id": f"call-{call_number}",
                    "status": "completed",
                },
            )
            return SimpleNamespace(output=[tool_call], output_text="")

    monkeypatch.setattr(
        "backend.app.services.formulation_agent.OpenAI",
        lambda **kwargs: SimpleNamespace(responses=FakeResponses()),
    )
    parsed = parse_csv_upload("tool-loop.csv", b"INCI,Concentration\nNIACINAMIDE,5%\n")
    output = OpenAIFormulationInterpreter(api_key="test")(parsed, store, catalogue, "gpt-5.6-sol")

    assert output.interpretation.ingredients[0].name_sources[0].source_value == "NIACINAMIDE"
    assert len([call for call in calls if call.get("tools")]) == 5
    assert calls[-1]["tools"] == []
    assert "Finish the structured interpretation now" in calls[-1]["input"][-1]["content"]


@pytest.mark.openai_integration
@pytest.mark.skipif(__import__("os").getenv("RUN_OPENAI_INTEGRATION") != "1", reason="live OpenAI checks are explicitly opt-in")
def test_live_openai_interpretation_is_optional(store, catalogue):
    from backend.app.config import load_settings

    settings = load_settings()
    if not settings.api_key:
        pytest.skip("OPENAI_API_KEY is not configured")
    parsed = parse_csv_upload(
        "synthetic-messy.csv",
        (
            "Regulens synthetic model check,,,\n"
            "Product Type,Toothpaste,,\n"
            ",,,\n"
            "RM Description,INCI Declaration,Usage,Remarks\n"
            "B3 Active,Niacinamide,5,unit intentionally absent\n"
            "Humectant,Glycerin,4%,explicit percent\n"
            "Water Phase,Aqua,balance,non-numeric\n"
            "Fragrance Base,Parfum,QS,non-numeric\n"
        ).encode()
    )
    model = settings.agent_model
    service = FormulationAgentService(
        store,
        catalogue,
        model_runner=OpenAIFormulationInterpreter(api_key=settings.api_key),
        model=model,
    )
    session = service.create(parsed)
    assert session.state != "failed"
    assert session.usage and session.usage.actual_model
    assert session.usage.actual_model.startswith(model)
    print(json.dumps({
        "model": session.usage.actual_model,
        "input_tokens": session.usage.input_tokens,
        "output_tokens": session.usage.output_tokens,
        "total_tokens": session.usage.total_tokens,
        "tool_calls": session.usage.tool_calls,
        "detected_rows": session.detected_table.data_rows,
        "clarification_questions": [question.question_type for question in session.questions],
        "final_state": session.state,
    }))

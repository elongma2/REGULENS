from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from backend.app.models.formulation import FormulationRequest
from backend.app.services.formulation import screen_formulation
from backend.app.services.loader import load_accepted_store
from backend.app.services.screening_report import build_screening_report


ROOT = Path(__file__).resolve().parents[2]


def test_report_discloses_partial_trade_material_coverage() -> None:
    request = FormulationRequest.model_validate({
        "formulation_id": "FORM-TRADE-PARTIAL",
        "formulation_name": "Trade material pilot",
        "assembly_scope": {
            "completeness": "partial",
            "issue_codes": [
                "incomplete_supplier_disclosure",
                "material_usage_missing",
            ],
            "unresolved_material_ids": ["material-1"],
            "incomplete_disclosure_material_ids": ["material-1"],
            "unresolved_association_ids": [],
            "source_document_ids": ["supplier-document-1"],
            "calculated_from_trade_materials": True,
        },
        "assembly_calculation_snapshot": {
            "source_documents": {
                "supplier-document-1": {
                    "original_filename": "Supplier Blend SDS.pdf",
                    "supplier_name": "Example Supplier",
                    "trade_name": "Supplier Blend",
                },
            },
            "materials": [{
                "material_id": "material-1",
                "trade_name": "Supplier Blend",
                "supplier_name": "Example Supplier",
            }],
            "aggregates": [{
                "display_name": "Tosylchloramide sodium",
                "aggregate_quantity": {"kind": "exact", "value": 0.1, "unit": "percent"},
                "contributions": [{
                    "source_material_id": "material-1",
                    "governing_document_id": "supplier-document-1",
                    "calculation_formula": "2% × 5% = 0.1%",
                    "source_evidence": [{"page": 2, "source_snippet": "Tosylchloramide sodium 5%"}],
                }],
            }],
        },
        "ingredients": [{
            "name": "Tosylchloramide sodium",
            "concentration": {
                "value": 0.1,
                "unit": "percent",
                "basis": None,
                "preparation_stage": "finished_product",
            },
        }],
    })
    response = screen_formulation(load_accepted_store(ROOT), request)
    assert response.ingredient_results[0].screening_disposition.value == "fully_evaluated"
    assert "assembly_incomplete" not in {
        issue.code for issue in response.ingredient_results[0].review_issues
    }
    assert response.formulation.assembly_scope.completeness == "partial"
    pdf = build_screening_report(response)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "Trade-material assembly coverage" in text
    assert "partial screening" in text
    assert "incomplete supplier disclosure" in text
    assert "material usage missing" in text
    assert "Calculated ingredient contributions" in text
    assert "2% × 5% = 0.1%" in text
    normalized_text = " ".join(text.split())
    assert "Supplier Blend · Example Supplier · Supplier Blend SDS.pdf · page 2" in normalized_text


def test_report_labels_qs_aqua_and_known_supplier_contribution() -> None:
    request = FormulationRequest.model_validate({
        "formulation_id": "FORM-QS-AQUA",
        "formulation_name": "Q.s. Aqua pilot",
        "assembly_scope": {
            "completeness": "partial",
            "issue_codes": ["constituent_concentration_missing"],
            "coverage_limitation_codes": ["constituent_concentration_missing"],
            "source_document_ids": ["formula.csv", "boundshift.pdf"],
        },
        "assembly_calculation_snapshot": {
            "source_documents": {
                "formula.csv": {"original_filename": "formula.csv"},
                "boundshift.pdf": {
                    "original_filename": "BoundShift X.pdf",
                    "trade_name": "BoundShift X",
                },
            },
            "materials": [{"material_id": "boundshift", "trade_name": "BoundShift X"}],
            "aggregates": [{
                "display_name": "AQUA",
                "aggregate_quantity": {
                    "kind": "lower_bound", "lower": 0.45, "unit": "percent",
                },
                "contributions": [{
                    "source_type": "direct_ingredient",
                    "governing_document_id": "formula.csv",
                    "finished_product_quantity": {
                        "kind": "unknown", "unit": "percent", "raw_text": "q.s. to 100%",
                    },
                    "calculation_formula": "Direct finished-product ingredient",
                }, {
                    "source_type": "material_constituent",
                    "source_material_id": "boundshift",
                    "governing_document_id": "boundshift.pdf",
                    "finished_product_quantity": {
                        "kind": "exact", "value": 0.45, "unit": "percent",
                    },
                    "calculation_formula": "1.5% × 30% ÷ 100 = 0.45%",
                }],
            }],
        },
        "ingredients": [{
            "name": "AQUA",
            "cas_number": "7732-18-5",
            "concentration": {
                "concentration_type": "lower_bound",
                "lower_bound": 0.45,
                "lower_inclusive": True,
                "unit": "percent",
                "basis": None,
                "preparation_stage": "finished_product",
            },
        }],
    })
    response = screen_formulation(load_accepted_store(ROOT), request)
    text = " ".join(
        "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(build_screening_report(response))).pages).split()
    )

    assert "q.s. to 100%; known supplier contribution 0.45%" in text


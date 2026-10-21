from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import OpenAISettings
from backend.app.main import create_app as build_app
from backend.app.services.loader import AcceptedBaselineError, load_accepted_store
from backend.app.services.ingredient_catalog import (
    AcceptedIdentityCatalogueError,
    load_accepted_ingredient_catalog,
)
from backend.app.services.source_rendering import (
    RENDER_DPI,
    SourceEvidenceRenderer,
    clamp_padded_bbox,
    render_cache_etag,
)


ROOT = Path(__file__).resolve().parents[2]


def create_app(*args, **kwargs):
    kwargs.setdefault("settings_loader", lambda: OpenAISettings(None, "gpt-5.6-sol", "gpt-5.6-luna"))
    return build_app(*args, **kwargs)


def concentration(value=0.2, unit="percent", basis=None, stage="finished_product"):
    return {
        "value": value,
        "unit": unit,
        "basis": basis,
        "preparation_stage": stage,
    }


def ingredient(name, value=0.2, **overrides):
    row = {"name": name, "concentration": concentration(value)}
    row.update(overrides)
    return row


@pytest.fixture(scope="module")
def store():
    return load_accepted_store(ROOT)


@pytest.fixture()
def client(store):
    with TestClient(create_app(lambda: store)) as test_client:
        yield test_client


def test_valid_one_ingredient_request(client):
    response = client.post(
        "/screen-formulation",
        json={
            "formulation_id": "FORM-001",
            "formulation_name": "Example rinse-off product",
            "ingredients": [ingredient("Tosylchloramide sodium")],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["formulation"]["formulation_id"] == "FORM-001"
    assert payload["summary"]["ingredients_submitted"] == 1
    assert payload["ingredient_results"][0]["submitted_row_number"] == 1


def test_health_reports_runtime_availability_without_secrets(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "regulatory_baseline": "available",
        "identity_catalogue": "available",
        "formulation_agent": "not_configured",
        "agent_model": "gpt-5.6-sol",
        "explanation_model": "gpt-5.6-luna",
        "persistence": "not_configured",
    }
    assert "OPENAI_API_KEY" not in response.text


def test_local_frontend_origin_is_allowed_without_wildcard_cors(client):
    response = client.options(
        "/screen-formulation",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-methods"] == "GET, POST, PATCH, DELETE, OPTIONS"
    assert response.headers["access-control-allow-origin"] != "*"


def test_screening_options_are_source_backed_and_unambiguous(client, store):
    response = client.get("/screening-options")
    assert response.status_code == 200
    payload = response.json()
    assert payload["jurisdiction"] == "Singapore"
    assert payload["dataset_version"] == store.dataset_version
    assert payload["accepted_baseline_sha256"] == store.baseline_manifest_hash
    assert len(payload["product_contexts"]) == 106
    assert len(set(payload["product_contexts"])) == 106
    assert payload["concentration_units"] == ["percent", "mg/kg", "ppm"]
    assert payload["concentration_bases"] == [
        None,
        "NH3",
        "free base",
        "zinc",
        "sulphate",
        "hydrochloride",
        "tetrahydrochloride",
    ]
    assert payload["preparation_stages"] == [
        "finished_product",
        "after_mixing",
        "ready_for_use",
    ]


def test_valid_multi_ingredient_aggregation(client):
    conditional_name = (
        "Diethylene glycol (except if it is present as an unavoidable trace\n"
        "amount up to a limit of 0.1% in the finished cosmetic product)"
    )
    response = client.post(
        "/screen-formulation",
        json={
            "formulation_id": "FORM-002",
            "formulation_name": "Mixed screening example",
            "ingredients": [
                {"name": "Aminophylline"},
                ingredient("Tosylchloramide sodium", 0.2),
                ingredient("Tosylchloramide sodium", 0.21),
                {"name": "Definitely absent ingredient"},
                {"name": conditional_name},
                ingredient("Chlorates of alkali metals", 1.0),
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    summary = payload["summary"]
    assert summary == {
        "ingredients_submitted": 6,
        "prohibited_substance_identified": 1,
        "restriction_exceeded": 1,
        "restriction_within_limit": 1,
        "professional_review_required": 1,
        "information_missing": 1,
        "identity_unresolved": 1,
        "no_issue_identified_within_scoped_rules": 0,
        "permitted_use_within_conditions": 0,
        "permitted_use_condition_not_met": 0,
        "regulated_function_not_permitted": 0,
        "total_requiring_review": 2,
        "total_unresolved_identities": 1,
        "duplicate_row_groups": [],
    }
    assert [item["submitted_row_number"] for item in payload["ingredient_results"]] == list(range(1, 7))


@pytest.mark.parametrize(
    "bad_concentration",
    [
        {"value": "abc%", "unit": "percent", "basis": None, "preparation_stage": "finished_product"},
        {"value": "0.3", "unit": "percent", "basis": None, "preparation_stage": "finished_product"},
        {"value": -0.1, "unit": "percent", "basis": None, "preparation_stage": "finished_product"},
        {"value": 100.1, "unit": "percent", "basis": None, "preparation_stage": "finished_product"},
        {"value": 0.3, "unit": "percent", "preparation_stage": "finished_product"},
        {"value": 0.3, "unit": "percent", "basis": "null", "preparation_stage": "finished_product"},
        {"value": 0.3, "unit": "%", "basis": None, "preparation_stage": "finished_product"},
        {"value": 0.3, "unit": "percent", "basis": None, "preparation_stage": "unspecified"},
    ],
)
def test_invalid_concentration_returns_422(client, bad_concentration):
    response = client.post(
        "/screen-formulation",
        json={"ingredients": [{"name": "Test ingredient", "concentration": bad_concentration}]},
    )
    assert response.status_code == 422


def test_nonfinite_concentration_returns_422(client):
    response = client.post(
        "/screen-formulation",
        content=(
            '{"ingredients":[{"name":"Test ingredient","concentration":'
            '{"value":NaN,"unit":"percent","basis":null,'
            '"preparation_stage":"finished_product"}}]}'
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("unit", ["mg/kg", "ppm"])
def test_nonpercentage_values_over_100_are_valid(client, unit):
    response = client.post(
        "/screen-formulation",
        json={
            "ingredients": [
                {
                    "name": "Definitely absent ingredient",
                    "concentration": concentration(1000.0, unit=unit),
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["ingredient_results"][0]["primary_finding"] == "identity_unresolved"


@pytest.mark.parametrize(
    "payload",
    [
        {"ingredients": []},
        {"ingredients": [{"name": " "}]},
        {"ingredients": [{"name": "Aminophylline", "cas_number": "123-45-6"}]},
        {"ingredients": [{"name": "Aminophylline", "cas_number": "1-11-6"}]},
        {"ingredients": [{"name": "Aminophylline", "unexpected": True}]},
        {"ingredients": "not-a-list"},
        {"formulation_name": " ", "ingredients": [{"name": "Aminophylline"}]},
    ],
)
def test_malformed_formulation_returns_422(client, payload):
    assert client.post("/screen-formulation", json=payload).status_code == 422


def test_unsupported_product_context_returns_422(client):
    response = client.post(
        "/screen-formulation",
        json={"product_context": "Invented context", "ingredients": [{"name": "Aminophylline"}]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_product_context"


def test_source_backed_context_is_accepted(client):
    response = client.post(
        "/screen-formulation",
        json={
            "product_context": "Toothpaste",
            "ingredients": [ingredient("Chlorates of alkali metals", 4.0)],
        },
    )
    assert response.status_code == 200
    assert response.json()["ingredient_results"][0]["primary_finding"] == "restriction_within_limit"


def test_duplicate_rows_are_preserved_and_reported(client):
    duplicate = ingredient("Tosylchloramide sodium", 0.1)
    response = client.post(
        "/screen-formulation",
        json={"ingredients": [duplicate, duplicate, {"name": "Aminophylline"}]},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["summary"]["ingredients_submitted"] == 3
    assert payload["summary"]["duplicate_row_groups"] == [[1, 2]]
    assert len(payload["ingredient_results"]) == 3


def test_evidence_and_accepted_baseline_identity_are_preserved(client, store):
    response = client.post(
        "/screen-formulation",
        json={"ingredients": [{"name": "Aminophylline", "cas_number": "317-34-0"}]},
    )
    payload = response.json()
    assert payload["dataset"]["dataset_version"] == store.dataset_version
    assert payload["dataset"]["accepted_baseline_sha256"] == store.baseline_manifest_hash
    assert len(payload["dataset"]["sources"]) == 4
    result = payload["ingredient_results"][0]
    assert result["dataset_version"] == store.dataset_version
    evidence = result["rule_evaluations"][0]["evidence"]
    assert evidence["source_text"] == "A1136 | Aminophylline"
    assert evidence["source_url"].startswith("https://sso.agc.gov.sg/")
    assert evidence["raw_record_id"]
    assert evidence["raw_fragments"][0]["row_bbox"]
    assert evidence["regulation_6_provisions"][0]["source_url"]
    assert evidence["acd_counterpart_rules"][0]["raw_fragments"][0]["row_bbox"]


def test_no_issue_count_uses_existing_core_result(store):
    synthetic = replace(
        store,
        rules_by_substance_id={
            **store.rules_by_substance_id,
            "substance-sg-third-schedule-i-a1136": (),
        },
    )
    with TestClient(create_app(lambda: synthetic)) as client:
        payload = client.post(
            "/screen-formulation", json={"ingredients": [{"name": "Aminophylline"}]}
        ).json()
    assert payload["summary"]["no_issue_identified_within_scoped_rules"] == 1


def test_integrity_failure_is_fail_closed():
    def failed_loader():
        raise AcceptedBaselineError("baseline hash mismatch")

    with TestClient(create_app(failed_loader)) as client:
        response = client.post(
            "/screen-formulation", json={"ingredients": [{"name": "Aminophylline"}]}
        )
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "accepted_baseline_integrity_failure",
        "message": "baseline hash mismatch",
    }


def test_screening_options_integrity_failure_is_fail_closed():
    def failed_loader():
        raise AcceptedBaselineError("baseline hash mismatch")

    with TestClient(create_app(failed_loader)) as client:
        response = client.get("/screening-options")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "accepted_baseline_integrity_failure"


def test_api_does_not_mutate_accepted_files(client):
    baseline = json.loads((ROOT / "data_pipeline" / "accepted_output_hashes.json").read_text(encoding="utf-8"))
    before = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in baseline["generated_output_hashes"]
    }
    assert client.post(
        "/screen-formulation", json={"ingredients": [{"name": "Aminophylline"}]}
    ).status_code == 200
    after = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in baseline["generated_output_hashes"]
    }
    assert before == after == baseline["generated_output_hashes"]


def test_response_has_no_product_level_conclusion(client):
    payload = client.post(
        "/screen-formulation", json={"ingredients": [{"name": "Aminophylline"}]}
    ).json()
    assert not {"compliant", "approved", "legal", "safe", "pass", "fail"}.intersection(payload)


@pytest.mark.parametrize(
    ("raw_record_id", "page", "reference"),
    [
        ("raw-singapore_regulations_2025_12_01-third-schedule-part-i-a1136", "13", "A1136"),
        ("raw-singapore_regulations_2025_12_01-third-schedule-part-ii-5", "99", "5"),
    ],
)
def test_source_evidence_crop_returns_accepted_png(client, raw_record_id, page, reference):
    response = client.get(f"/source-evidence/{raw_record_id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["x-source-pages"] == page
    assert response.headers["x-source-reference"] == reference
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"].startswith('"')


def test_source_evidence_full_page_and_conditional_request(client):
    raw_record_id = "raw-singapore_regulations_2025_12_01-third-schedule-part-ii-5"
    crop = client.get(f"/source-evidence/{raw_record_id}")
    page = client.get(f"/source-evidence/{raw_record_id}/page")
    assert page.status_code == 200
    assert page.headers["x-render-mode"] == "page"
    assert len(page.content) > len(crop.content)
    cached = client.get(
        f"/source-evidence/{raw_record_id}/page",
        headers={"If-None-Match": page.headers["etag"]},
    )
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["etag"] == page.headers["etag"]


def test_source_evidence_unknown_record_fails_safely(client):
    response = client.get("/source-evidence/not-an-accepted-record")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "source_evidence_not_found"


def test_identity_source_evidence_returns_accepted_row_and_full_page(client):
    raw_record_id = "raw-eu-2025-1175-entry-17380"
    crop = client.get(f"/identity-source-evidence/{raw_record_id}")
    page = client.get(f"/identity-source-evidence/{raw_record_id}/page")

    assert crop.status_code == 200
    assert crop.headers["content-type"] == "image/png"
    assert crop.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert crop.headers["x-source-reference"] == "17380"
    assert crop.headers["x-source-pages"] == "516"
    assert crop.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert page.status_code == 200
    assert page.headers["x-render-mode"] == "page"
    assert len(page.content) > len(crop.content)

    cached = client.get(
        f"/identity-source-evidence/{raw_record_id}/page",
        headers={"If-None-Match": page.headers["etag"]},
    )
    assert cached.status_code == 304
    assert cached.content == b""


def test_identity_source_evidence_uses_only_trusted_catalogue_coordinates(client):
    raw_record_id = "raw-eu-2025-1175-entry-17380"
    accepted = client.get(f"/identity-source-evidence/{raw_record_id}")
    supplied = client.get(
        f"/identity-source-evidence/{raw_record_id}",
        params={"path": "C:/Windows/system.ini", "page": 1, "bbox": "0,0,1,1"},
    )

    assert supplied.status_code == 200
    assert supplied.headers["etag"] == accepted.headers["etag"]
    assert supplied.content == accepted.content


def test_identity_source_evidence_unknown_record_fails_safely(client):
    response = client.get("/identity-source-evidence/not-an-accepted-record")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "identity_source_evidence_not_found"


def test_client_coordinates_and_paths_cannot_change_source_render(client):
    raw_record_id = "raw-singapore_regulations_2025_12_01-third-schedule-part-i-a1136"
    accepted = client.get(f"/source-evidence/{raw_record_id}")
    supplied = client.get(
        f"/source-evidence/{raw_record_id}",
        params={"path": "C:/Windows/system.ini", "source": "other", "page": 1, "bbox": "0,0,1,1"},
    )
    assert supplied.status_code == 200
    assert supplied.headers["etag"] == accepted.headers["etag"]
    assert supplied.content == accepted.content


def test_crop_padding_is_clamped_to_page_bounds():
    assert clamp_padded_bbox([1, 0, 99, 100], [1, 1, 99, 10], 100, 100) == (0.0, 0.0, 100.0, 34.0)
    assert clamp_padded_bbox([1, 0, 99, 100], [1, 90, 99, 99], 100, 100) == (0.0, 66.0, 100.0, 100.0)


def test_source_render_cache_identity_includes_all_accepted_dimensions(store):
    raw_id = "raw-singapore_regulations_2025_12_01-third-schedule-part-i-a1136"
    source_hash = store.source_documents_by_id["singapore_regulations_2025_12_01"]["sha256"]
    baseline = render_cache_etag(store.dataset_version, source_hash, raw_id, "crop", RENDER_DPI)
    alternatives = {
        render_cache_etag("new-dataset", source_hash, raw_id, "crop", RENDER_DPI),
        render_cache_etag(store.dataset_version, "0" * 64, raw_id, "crop", RENDER_DPI),
        render_cache_etag(store.dataset_version, source_hash, "other-record", "crop", RENDER_DPI),
        render_cache_etag(store.dataset_version, source_hash, raw_id, "page", RENDER_DPI),
        render_cache_etag(store.dataset_version, source_hash, raw_id, "crop", 144),
    }
    assert baseline not in alternatives
    assert len(alternatives) == 5


def test_continuation_fragments_are_composed(store):
    raw_id = "raw-singapore_regulations_2025_12_01-third-schedule-part-i-a1136"
    original = store.raw_by_id[raw_id]
    continued = {**original, "fragments": [*original["fragments"], *original["fragments"]]}
    synthetic = replace(store, raw_by_id={**store.raw_by_id, raw_id: continued})
    single = SourceEvidenceRenderer(store).render(raw_id, "crop")
    double = SourceEvidenceRenderer(synthetic).render(raw_id, "crop")
    with Image.open(io.BytesIO(single.content)) as single_image, Image.open(io.BytesIO(double.content)) as double_image:
        assert double_image.height > single_image.height * 2


def test_source_hash_mismatch_fails_only_evidence_route(store):
    source_id = "singapore_regulations_2025_12_01"
    changed_source = {**store.source_documents_by_id[source_id], "sha256": "0" * 64}
    synthetic = replace(
        store,
        source_documents_by_id={**store.source_documents_by_id, source_id: changed_source},
    )
    with TestClient(create_app(lambda: synthetic)) as synthetic_client:
        image_response = synthetic_client.get(
            "/source-evidence/raw-singapore_regulations_2025_12_01-third-schedule-part-i-a1136"
        )
        screening_response = synthetic_client.post(
            "/screen-formulation", json={"ingredients": [{"name": "Aminophylline"}]}
        )
    assert image_response.status_code == 503
    assert image_response.json()["detail"]["code"] == "source_evidence_unavailable"
    assert screening_response.status_code == 200


def test_simple_diethylene_glycol_uses_literal_source_backed_regulatory_alias(client):
    response = client.post(
        "/screen-formulation", json={"ingredients": [{"name": "Diethylene glycol"}]}
    )
    assert response.status_code == 200
    result = response.json()["ingredient_results"][0]
    assert result["primary_finding"] == "professional_review_required"
    assert result["identity"]["identity_source_type"] == "singapore_regulatory_source"
    assert "derived_source_name_except_clause" in result["identity"]["match_methods"]
    assert result["review_types"] == ["rule_review"]
    assert result["rule_evaluations"][0]["rule_id"] == "sg-third-schedule-i-a1140"


def test_ingredient_search_exact_prefix_contains_and_bounds(client):
    exact = client.get("/ingredients", params={"query": "niacinamide"})
    assert exact.status_code == 200
    exact_payload = exact.json()
    assert exact_payload["results"][0]["canonical_name"] == "NIACINAMIDE"
    assert exact_payload["results"][0]["identity_source"] == "EU Glossary of Common Ingredient Names"
    assert "regulatory_status" not in exact_payload["results"][0]

    prefix = client.get("/ingredients", params={"query": "nia", "limit": 3}).json()["results"]
    assert len(prefix) == 3
    assert all("nia" in item["canonical_name"].casefold() for item in prefix)
    assert prefix[0]["canonical_name"].startswith("NIA")

    contains = client.get("/ingredients", params={"query": "acinam", "limit": 20}).json()["results"]
    assert any(item["canonical_name"] == "NIACINAMIDE" for item in contains)
    assert client.get("/ingredients", params={"query": "x"}).status_code == 422
    assert client.get("/ingredients", params={"query": "nia", "limit": 21}).status_code == 422


def test_niacinamide_is_catalogue_resolved_with_bounded_no_listing_result(client):
    result = client.post("/screen-formulation", json={"ingredients": [{"name": "Niacinamide"}]}).json()["ingredient_results"][0]
    assert result["primary_finding"] == "no_issue_identified_within_scoped_rules"
    assert result["identity"]["catalogue_identity"]["canonical_name"] == "NIACINAMIDE"
    assert result["identity"]["singapore_linkage_status"] == "not_applicable"
    assert result["review_required"] is False
    assert result["review_types"] == []
    assert result["searched_regulatory_sections"] == [
        "Third Schedule Part I",
        "Third Schedule Part II",
        "Annex II Part 1",
        "Annex III Part 1",
        "Third Schedule Part III",
        "Third Schedule Part IV",
        "Third Schedule Part V",
        "Annex IV Part 1",
        "Annex VI",
        "Annex VII",
    ]
    assert result["rule_evaluations"] == []


def test_formulation_response_marks_historical_linkage_layer_inactive(client):
    payload = client.post(
        "/screen-formulation", json={"ingredients": [{"name": "Niacinamide"}]}
    ).json()
    linkage = payload["dataset"]["identity_linkage"]
    assert linkage["available"] is False
    assert linkage["dataset_version"] is None
    assert linkage["screened_scope"] == []


def test_regulatory_identity_precedes_catalogue(client):
    aminophylline = client.post("/screen-formulation", json={"ingredients": [{"name": "Aminophylline"}]}).json()["ingredient_results"][0]
    assert aminophylline["primary_finding"] == "prohibited_substance_identified"
    assert aminophylline["identity"]["identity_source_type"] in {"singapore_regulatory_source", "acd_regulatory_source"}
    assert aminophylline["identity"]["singapore_linkage_status"] == "not_applicable"
    assert aminophylline["identity"]["catalogue_identity"] is None


def test_catalogue_failure_does_not_disable_existing_regulatory_screening(store):
    def unavailable():
        raise AcceptedIdentityCatalogueError("identity hash mismatch")

    with TestClient(create_app(lambda: store, unavailable)) as unavailable_client:
        search = unavailable_client.get("/ingredients", params={"query": "nia"})
        aminophylline = unavailable_client.post("/screen-formulation", json={"ingredients": [{"name": "Aminophylline"}]})
        unknown = unavailable_client.post("/screen-formulation", json={"ingredients": [{"name": "Niacinamide"}]})
    assert search.status_code == 503
    assert search.json()["detail"]["code"] == "accepted_identity_baseline_integrity_failure"
    assert aminophylline.status_code == 200
    assert aminophylline.json()["ingredient_results"][0]["primary_finding"] == "prohibited_substance_identified"
    unknown_result = unknown.json()["ingredient_results"][0]
    assert unknown_result["primary_finding"] == "professional_review_required"
    assert unknown_result["review_reasons"] == ["ingredient_catalogue_unavailable_identity_verification_withheld"]
    assert unknown_result["review_types"] == ["identity_review"]


def test_acd_regulatory_search_exact_prefix_contains_and_limits(client):
    exact = client.get("/acd-ingredients", params={"query": "hydroquinone", "limit": 2})
    assert exact.status_code == 200
    exact_results = exact.json()["results"]
    assert len(exact_results) == 2
    assert exact_results[0]["name"].casefold().startswith("hydroquinone")
    assert set(exact_results[0]) >= {
        "rule_id", "name", "annex", "reference", "cas_numbers", "source_pages",
        "raw_record_id", "source_version", "source_url", "manual_review_required",
    }
    assert "allowed" not in exact_results[0]
    assert "regulatory_status" not in exact_results[0]
    crop = client.get(f"/source-evidence/{exact_results[0]['raw_record_id']}")
    assert crop.status_code == 200
    assert crop.headers["content-type"] == "image/png"

    prefix = client.get("/acd-ingredients", params={"query": "hydro", "limit": 20})
    assert prefix.status_code == 200
    assert prefix.json()["results"]
    contains = client.get("/acd-ingredients", params={"query": "quinone", "limit": 20})
    assert contains.status_code == 200
    assert contains.json()["results"]
    assert client.get("/acd-ingredients", params={"query": "x"}).status_code == 422
    assert client.get("/acd-ingredients", params={"query": "  "}).status_code == 422
    assert client.get("/acd-ingredients", params={"query": "hydro", "limit": 21}).status_code == 422

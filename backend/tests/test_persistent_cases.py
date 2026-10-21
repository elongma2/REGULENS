from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import OpenAISettings
from backend.app.main import create_app
from backend.app.services.supabase_gateway import AuthenticatedUser, CaseDeletionError, ResourceNotFoundError


USER_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ORG_A = UUID("11111111-1111-4111-8111-111111111111")
ORG_B = UUID("22222222-2222-4222-8222-222222222222")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakePersistentGateway:
    """Small trusted-repository fake used to exercise HTTP authorization boundaries."""

    def __init__(self) -> None:
        self.organisations = {USER_A: ORG_A, USER_B: ORG_B}
        self.cases: dict[str, dict] = {}
        self.versions: dict[str, dict] = {}
        self.screenings: list[dict] = []
        self.review_items: list[dict] = []
        self.clarifications: list[dict] = []
        self.notes: list[dict] = []
        self.follow_ups: list[dict] = []

    def verify_user(self, token: str) -> AuthenticatedUser:
        users = {
            "token-a": AuthenticatedUser(USER_A, "a@example.test"),
            "token-b": AuthenticatedUser(USER_B, "b@example.test"),
        }
        if token not in users:
            raise PermissionError("invalid token")
        return users[token]

    def me(self, user: AuthenticatedUser) -> dict:
        organisation = self.organisations[user.id]
        return {
            "id": str(user.id), "email": user.email, "display_name": "Pilot User",
            "default_organisation_id": str(organisation),
            "organisations": [{"id": str(organisation), "name": "Pilot Workspace", "role": "owner", "created_at": _now()}],
        }

    def _case(self, user_id: UUID, case_id: UUID | str) -> dict:
        row = self.cases.get(str(case_id))
        if row is None or row["organisation_id"] != str(self.organisations[user_id]):
            raise ResourceNotFoundError("Case not found")
        return row

    def list_cases(self, user_id: UUID) -> list[dict]:
        rows = []
        for stored in self.cases.values():
            if stored["organisation_id"] != str(self.organisations[user_id]):
                continue
            row = deepcopy(stored)
            versions = self.list_formulations(user_id, row["id"])
            row["formulations"] = versions
            row["latest_formulation"] = versions[0] if versions else None
            row["latest_finding_count"] = None
            overview = self.review_overview(user_id, row["id"])
            row["review_summary"] = {
                "latest_screening_run_id": overview["latest_screening_run_id"],
                "latest_screening_formulation_version_id": overview["latest_screening_formulation_version_id"],
                "latest_screening_at": overview["latest_screening_at"],
                "attention_results": overview["attention_findings"],
                "reviewer_items_remaining": overview["not_reviewed"] + overview["in_review"] + overview["awaiting_information"],
                "open_follow_ups": overview["open_follow_ups"],
                "unresolved_clarifications": overview["unresolved_clarifications"],
                "last_review_activity_at": overview["last_review_activity_at"],
            }
            rows.append(row)
        return sorted(rows, key=lambda item: item["updated_at"], reverse=True)

    def create_case(self, user_id: UUID, payload: dict) -> dict:
        case_id = uuid4(); timestamp = _now()
        row = {
            "id": str(case_id), "organisation_id": str(self.organisations[user_id]),
            "name": payload["name"], "client_name": payload.get("client_name"), "product_type": None,
            "status": "active", "created_by": str(user_id), "created_at": timestamp,
            "updated_at": timestamp, "archived_at": None,
        }
        self.cases[str(case_id)] = row
        return deepcopy(row)

    def get_case(self, user_id: UUID, case_id: UUID | str) -> dict:
        row = deepcopy(self._case(user_id, case_id))
        row["formulations"] = self.list_formulations(user_id, case_id)
        return row

    def update_case(self, user_id: UUID, case_id: UUID | str, changes: dict) -> dict:
        row = self._case(user_id, case_id); row.update(changes); row["updated_at"] = _now()
        return deepcopy(row)

    def delete_case(self, user_id: UUID, case_id: UUID | str) -> None:
        self._case(user_id, case_id)
        del self.cases[str(case_id)]
        version_ids = [key for key, value in self.versions.items() if value["case_id"] == str(case_id)]
        for version_id in version_ids:
            del self.versions[version_id]
        screening_ids = {item["id"] for item in self.screenings if item.get("formulation_version_id") in version_ids}
        self.screenings = [item for item in self.screenings if item["formulation_version_id"] not in version_ids]
        self.review_items = [item for item in self.review_items if item.get("screening_run_id") not in screening_ids]
        self.clarifications = [item for item in self.clarifications if item.get("formulation_version_id") not in version_ids]
        self.notes = [item for item in self.notes if item.get("case_id") != str(case_id)]
        self.follow_ups = [item for item in self.follow_ups if item.get("case_id") != str(case_id)]

    def list_formulations(self, user_id: UUID, case_id: UUID | str) -> list[dict]:
        self._case(user_id, case_id)
        rows = [deepcopy(row) for row in self.versions.values() if row["case_id"] == str(case_id)]
        return sorted(rows, key=lambda item: item["version_number"], reverse=True)

    def get_version(self, user_id: UUID, version_id: UUID | str) -> dict:
        row = self.versions.get(str(version_id))
        if row is None:
            raise ResourceNotFoundError("Formulation version not found")
        self._case(user_id, row["case_id"])
        return deepcopy(row)

    def insert_screening(self, user_id: UUID, version_id: UUID, dataset_id: str, jurisdiction: str, request_snapshot: dict, result_snapshot: dict) -> dict:
        self.get_version(user_id, version_id)
        row = {
            "id": str(uuid4()), "formulation_version_id": str(version_id),
            "regulatory_dataset_id": dataset_id, "jurisdiction": jurisdiction,
            "request_snapshot": deepcopy(request_snapshot), "result_snapshot": deepcopy(result_snapshot),
            "created_by": str(user_id), "created_at": _now(),
        }
        self.screenings.append(row)
        for result in result_snapshot.get("ingredient_results", []):
            finding = result["primary_finding"]
            attention = bool(result.get("review_required")) or finding in {
                "prohibited_substance_identified", "restriction_exceeded", "professional_review_required",
                "information_missing", "identity_unresolved",
            }
            self.review_items.append({
                "id": str(uuid4()), "screening_run_id": row["id"], "subject_type": "formulation_ingredient_result",
                "subject_key": f"ingredient:{result['submitted_row_number']}",
                "submitted_row_number": result["submitted_row_number"], "engine_finding": finding,
                "requires_attention": attention, "review_status": "not_reviewed" if attention else None,
                "updated_by": str(user_id), "created_at": _now(), "updated_at": _now(), "reviewed_at": None,
            })
        return deepcopy(row)

    def list_screenings(self, user_id: UUID, version_id: UUID | str) -> list[dict]:
        self.get_version(user_id, version_id)
        return [deepcopy(item) for item in reversed(self.screenings) if item["formulation_version_id"] == str(version_id)]

    def get_screening(self, user_id: UUID, screening_id: UUID | str) -> dict:
        row = next((item for item in self.screenings if item["id"] == str(screening_id)), None)
        if row is None:
            raise ResourceNotFoundError("Screening run not found")
        self.get_version(user_id, row["formulation_version_id"])
        return deepcopy(row)

    def review_overview(self, user_id: UUID, case_id: UUID | str) -> dict:
        case = self._case(user_id, case_id)
        versions = self.list_formulations(user_id, case_id)
        current = versions[0] if versions else None
        runs = [run for version in versions for run in self.list_screenings(user_id, version["id"])]
        run = max(runs, key=lambda item: item["created_at"], default=None)
        items = [item for item in self.review_items if run and item["screening_run_id"] == run["id"]]
        statuses = {key: sum(item["review_status"] == key for item in items) for key in ("not_reviewed", "in_review", "awaiting_information", "reviewed")}
        notes = [item for item in self.notes if item["case_id"] == str(case_id)]
        follow_ups = [item for item in self.follow_ups if item["case_id"] == str(case_id)]
        return {
            "case_id": case["id"], "current_formulation_version_id": current["id"] if current else None,
            "latest_screening_run_id": run["id"] if run else None, "latest_screening_at": run["created_at"] if run else None,
            "latest_screening_formulation_version_id": run["formulation_version_id"] if run else None,
            "ingredients_screened": len((run or {}).get("result_snapshot", {}).get("ingredient_results", [])),
            "attention_findings": sum(item["requires_attention"] for item in items), **statuses,
            "open_follow_ups": sum(item["status"] == "open" for item in follow_ups), "unresolved_clarifications": 0,
            "note_count": len(notes), "last_review_activity_at": None, "recent_case_notes": [],
            "open_follow_up_items": [deepcopy(item) for item in follow_ups if item["status"] == "open"],
        }

    def review_workspace(self, user_id: UUID, version_id: UUID | str, screening_run_id: UUID | str | None = None) -> dict:
        version = self.get_version(user_id, version_id)
        runs = self.list_screenings(user_id, version_id)
        run = self.get_screening(user_id, screening_run_id) if screening_run_id else (runs[0] if runs else None)
        if run and run["formulation_version_id"] != str(version_id):
            raise ResourceNotFoundError("Screening run not found")
        case_id = version["case_id"]
        return {
            "case_id": case_id, "formulation_version_id": str(version_id), "screening_run_id": run["id"] if run else None,
            "clarification_targets": [],
            "review_items": [deepcopy(item) for item in self.review_items if run and item["screening_run_id"] == run["id"]],
            "notes": [deepcopy(item) for item in self.notes if item["case_id"] == case_id],
            "follow_ups": [deepcopy(item) for item in self.follow_ups if item["case_id"] == case_id],
        }

    def update_review_status(self, user_id: UUID, review_item_id: UUID, status: str) -> dict:
        item = next((item for item in self.review_items if item["id"] == str(review_item_id)), None)
        if item is None:
            raise ResourceNotFoundError("Review item not found")
        run = self.get_screening(user_id, item["screening_run_id"])
        self.get_version(user_id, run["formulation_version_id"])
        item.update({"review_status": status, "updated_by": str(user_id), "updated_at": _now(), "reviewed_at": _now() if status == "reviewed" else None})
        return deepcopy(item)

    def create_reviewer_note(self, user_id: UUID, case_id: UUID, target_type: str, target_id: UUID | None, body: str) -> dict:
        self._case(user_id, case_id)
        row = {
            "id": str(uuid4()), "case_id": str(case_id), "formulation_version_id": None,
            "clarification_id": str(target_id) if target_type == "clarification" else None,
            "review_item_id": str(target_id) if target_type == "review_item" else None,
            "target_type": target_type, "body": body, "created_by": str(user_id), "author_name": "Pilot User", "created_at": _now(),
        }
        if target_type == "formulation": row["formulation_version_id"] = str(target_id)
        self.notes.append(row); return deepcopy(row)

    def create_follow_up(self, user_id: UUID, case_id: UUID, target_type: str, target_id: UUID | None, action_text: str, details: str | None) -> dict:
        self._case(user_id, case_id); timestamp = _now()
        row = {
            "id": str(uuid4()), "case_id": str(case_id), "formulation_version_id": None,
            "clarification_id": str(target_id) if target_type == "clarification" else None,
            "review_item_id": str(target_id) if target_type == "review_item" else None,
            "target_type": target_type, "action_text": action_text, "details": details, "status": "open",
            "created_by": str(user_id), "author_name": "Pilot User", "resolved_by": None,
            "created_at": timestamp, "updated_at": timestamp, "resolved_at": None,
        }
        if target_type == "formulation": row["formulation_version_id"] = str(target_id)
        self.follow_ups.append(row); return deepcopy(row)

    def update_follow_up(self, user_id: UUID, follow_up_id: UUID, changes: dict) -> dict:
        item = next((item for item in self.follow_ups if item["id"] == str(follow_up_id)), None)
        if item is None:
            raise ResourceNotFoundError("Follow-up not found")
        self._case(user_id, item["case_id"]); item.update(changes); item["updated_at"] = _now()
        if item["status"] == "resolved": item.update({"resolved_by": str(user_id), "resolved_at": _now()})
        return deepcopy(item)

    def case_activity(self, user_id: UUID, case_id: UUID | str) -> dict:
        case = self._case(user_id, case_id)
        versions = self.list_formulations(user_id, case_id)
        version_by_id = {item["id"]: item for item in versions}
        runs = [item for item in self.screenings if item["formulation_version_id"] in version_by_id]
        run_by_id = {item["id"]: item for item in runs}
        run_numbers: dict[str, int] = {}
        for version in versions:
            version_runs = sorted((item for item in runs if item["formulation_version_id"] == version["id"]), key=lambda item: item["created_at"])
            run_numbers.update({item["id"]: index + 1 for index, item in enumerate(version_runs)})
        item_by_id = {item["id"]: item for item in self.review_items if item["screening_run_id"] in run_by_id}
        clarification_by_id = {item["id"]: item for item in self.clarifications if item["formulation_version_id"] in version_by_id}

        def context(row: dict) -> dict:
            review_item = item_by_id.get(row.get("review_item_id") or row.get("id")) if row.get("review_item_id") or row.get("screening_run_id") else None
            clarification = clarification_by_id.get(row.get("clarification_id"))
            run = run_by_id.get((review_item or {}).get("screening_run_id"))
            version_id = (run or {}).get("formulation_version_id") or (clarification or {}).get("formulation_version_id") or row.get("formulation_version_id")
            version = version_by_id.get(version_id)
            submitted_row = (review_item or {}).get("submitted_row_number")
            result = next((value for value in (run or {}).get("result_snapshot", {}).get("ingredient_results", []) if value.get("submitted_row_number") == submitted_row), None)
            ingredient = ((result or {}).get("submitted_ingredient") or {}).get("name")
            target_type = "finding" if review_item else "clarification" if clarification else "formulation" if version else "case"
            target_label = f"Finding · Row {submitted_row}" if review_item else f"Clarification · Row {(clarification or {}).get('source_row_number')}" if clarification else f"Version {version['version_number']}" if version else "Case"
            return {
                "case_id": case["id"], "case_name": case["name"], "target_type": target_type,
                "target_label": target_label, "formulation_version_id": version_id,
                "formulation_version_number": (version or {}).get("version_number"),
                "screening_run_id": (run or {}).get("id"), "screening_run_number": run_numbers.get((run or {}).get("id")),
                "screening_at": (run or {}).get("created_at"), "regulatory_dataset_id": (run or {}).get("regulatory_dataset_id"),
                "clarification_id": (clarification or {}).get("id"), "clarification_question_key": (clarification or {}).get("question_key"),
                "clarification_question": (clarification or {}).get("question"), "source_row_number": (clarification or {}).get("source_row_number"),
                "review_item_id": (review_item or {}).get("id"), "submitted_row_number": submitted_row,
                "ingredient_name": ingredient, "engine_finding": (review_item or {}).get("engine_finding"),
            }

        entries = [{"id": item["id"], "kind": "note", "occurred_at": item["created_at"], "author_name": item["author_name"], "context": context(item), "body": item["body"]} for item in self.notes if item["case_id"] == str(case_id)]
        entries += [{"id": item["id"], "kind": "follow_up", "occurred_at": item["updated_at"], "author_name": item["author_name"], "context": context(item), "action_text": item["action_text"], "details": item["details"], "status": item["status"], "created_at": item["created_at"], "updated_at": item["updated_at"], "resolved_at": item["resolved_at"], "resolved_by_name": "Pilot User" if item["resolved_by"] else None} for item in self.follow_ups if item["case_id"] == str(case_id)]
        entries += [{"id": item["id"], "kind": "review_update", "occurred_at": item["updated_at"], "author_name": "Pilot User", "context": context(item), "review_status": item["review_status"]} for item in item_by_id.values() if item.get("review_status") and item["updated_at"] != item["created_at"]]
        entries.sort(key=lambda item: item["occurred_at"], reverse=True)
        return {"case_id": case["id"], "entries": entries}


@pytest.fixture()
def persistent_client():
    gateway = FakePersistentGateway()
    with TestClient(_persistent_application(gateway)) as client:
        yield client, gateway


def _persistent_application(gateway: FakePersistentGateway):
    settings = OpenAISettings(None, "gpt-5.6-sol", "gpt-5.6-luna")
    return create_app(
        settings_loader=lambda: settings,
        supabase_gateway_factory=lambda _: gateway,
    )


def _auth(token: str = "token-a") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_cases_require_authentication(persistent_client):
    client, _ = persistent_client
    response = client.get("/cases")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"

    scratch = {
        "formulation_id": "SCRATCH-1", "formulation_name": "Scratch", "product_context": None,
        "ingredients": [{"name": "NIACINAMIDE", "cas_number": None, "concentration": None}],
    }
    assert client.post("/screen-formulation", json=scratch).status_code == 401
    assert client.post("/screen-formulation", headers=_auth(), json=scratch).status_code == 200


def test_case_is_private_and_can_be_reopened(persistent_client):
    client, _ = persistent_client
    created = client.post("/cases", headers=_auth(), json={"name": "Facial Serum", "client_name": "ABC Cosmetics"})
    assert created.status_code == 201
    case_id = created.json()["id"]

    reopened = client.get(f"/cases/{case_id}", headers=_auth())
    assert reopened.status_code == 200
    assert reopened.json()["name"] == "Facial Serum"

    assert client.get(f"/cases/{case_id}", headers=_auth("token-b")).status_code == 404
    assert client.patch(f"/cases/{case_id}", headers=_auth("token-b"), json={"name": "Stolen"}).status_code == 404
    assert client.delete(f"/cases/{case_id}", headers=_auth("token-b")).status_code == 404


def test_persisted_version_survives_new_app_and_screening_runs_are_immutable_snapshots(persistent_client):
    client, gateway = persistent_client
    case_id = client.post("/cases", headers=_auth(), json={"name": "Facial Serum"}).json()["id"]
    version_id = str(uuid4()); timestamp = _now()
    gateway.versions[version_id] = {
        "id": version_id, "case_id": case_id, "version_number": 1,
        "original_filename": "serum.csv", "status": "ready_to_screen", "revision": 3,
        "created_at": timestamp, "updated_at": timestamp, "screening_count": 0,
        "raw_extraction": {"filename": "serum.csv", "delimiter": ",", "rows": [["Ingredient"], ["NIACINAMIDE"]]},
        "agent_session": None,
        "canonical_formulation": {
            "formulation_id": "SERUM-1", "formulation_name": "Facial Serum", "product_context": None,
            "ingredients": [{"name": "NIACINAMIDE", "cas_number": None, "concentration": None}],
        },
        "product_context": None,
    }

    with TestClient(_persistent_application(gateway)) as restarted_client:
        reopened = restarted_client.get(f"/formulations/{version_id}", headers=_auth())
        assert reopened.status_code == 200
        assert reopened.json()["raw_extraction"]["filename"] == "serum.csv"
    assert client.get(f"/formulations/{version_id}", headers=_auth("token-b")).status_code == 404

    first = client.post(f"/formulations/{version_id}/screen", headers=_auth())
    second = client.post(f"/formulations/{version_id}/screen", headers=_auth())
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["result_snapshot"] == second.json()["result_snapshot"]
    runs = client.get(f"/formulations/{version_id}/screenings", headers=_auth()).json()
    assert len(runs) == 2


def test_case_delete_cascades_fake_versions_and_screenings(persistent_client):
    client, gateway = persistent_client
    case_id = client.post("/cases", headers=_auth(), json={"name": "Delete Me"}).json()["id"]
    version_id = str(uuid4()); timestamp = _now()
    gateway.versions[version_id] = {
        "id": version_id, "case_id": case_id, "version_number": 1, "original_filename": "delete.csv",
        "status": "uploaded", "revision": 0, "created_at": timestamp, "updated_at": timestamp,
        "screening_count": 0, "raw_extraction": {}, "agent_session": None,
        "canonical_formulation": None, "product_context": None,
    }
    screening_id = str(uuid4())
    gateway.screenings.append({"id": screening_id, "formulation_version_id": version_id})
    gateway.review_items.append({"id": str(uuid4()), "screening_run_id": screening_id})
    gateway.clarifications.append({"id": str(uuid4()), "formulation_version_id": version_id})
    gateway.notes.append({"id": str(uuid4()), "case_id": case_id})
    gateway.follow_ups.append({"id": str(uuid4()), "case_id": case_id})
    assert client.delete(f"/cases/{case_id}", headers=_auth()).status_code == 204
    assert case_id not in gateway.cases
    assert version_id not in gateway.versions
    assert gateway.screenings == []
    assert gateway.review_items == []
    assert gateway.clarifications == []
    assert gateway.notes == []
    assert gateway.follow_ups == []


def test_case_delete_returns_retryable_error_when_cleanup_fails():
    class FailingDeleteGateway(FakePersistentGateway):
        def delete_case(self, user_id: UUID, case_id: UUID | str) -> None:
            self._case(user_id, case_id)
            raise CaseDeletionError("Uploaded files could not be removed. The case was kept so you can retry.")

    gateway = FailingDeleteGateway()
    with TestClient(_persistent_application(gateway)) as client:
        case_id = client.post("/cases", headers=_auth(), json={"name": "Keep Me"}).json()["id"]
        response = client.delete(f"/cases/{case_id}", headers=_auth())
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "case_deletion_failed"
        assert case_id in gateway.cases


def test_review_workspace_keeps_human_state_separate_and_private(persistent_client):
    client, gateway = persistent_client
    case_id = client.post("/cases", headers=_auth(), json={"name": "Review Case"}).json()["id"]
    version_id = str(uuid4()); timestamp = _now()
    gateway.versions[version_id] = {
        "id": version_id, "case_id": case_id, "version_number": 1, "original_filename": "review.csv",
        "status": "screened", "revision": 1, "created_at": timestamp, "updated_at": timestamp,
        "screening_count": 1, "raw_extraction": {}, "agent_session": None,
        "canonical_formulation": None, "product_context": None,
    }
    run = gateway.insert_screening(USER_A, UUID(version_id), "dataset-1", "Singapore", {}, {
        "ingredient_results": [{
            "submitted_row_number": 1, "primary_finding": "information_missing", "review_required": True,
        }],
    })

    workspace = client.get(
        f"/formulations/{version_id}/review-workspace?screening_run_id={run['id']}", headers=_auth(),
    )
    assert workspace.status_code == 200
    item = workspace.json()["review_items"][0]
    assert item["review_status"] == "not_reviewed"
    assert client.get(f"/formulations/{version_id}/review-workspace", headers=_auth("token-b")).status_code == 404

    updated = client.patch(
        f"/review-items/{item['id']}", headers=_auth(), json={"review_status": "awaiting_information"},
    )
    assert updated.status_code == 200
    assert updated.json()["review_status"] == "awaiting_information"
    assert gateway.screenings[0]["result_snapshot"]["ingredient_results"][0]["primary_finding"] == "information_missing"

    note = client.post(f"/cases/{case_id}/review-notes", headers=_auth(), json={
        "target_type": "review_item", "target_id": item["id"], "body": "Confirm the concentration basis.",
    })
    follow_up = client.post(f"/cases/{case_id}/follow-ups", headers=_auth(), json={
        "target_type": "review_item", "target_id": item["id"], "action_text": "Request the missing basis.",
    })
    assert note.status_code == follow_up.status_code == 201
    resolved = client.patch(
        f"/follow-ups/{follow_up.json()['id']}", headers=_auth(), json={"status": "resolved"},
    )
    assert resolved.json()["status"] == "resolved"

    overview = client.get(f"/cases/{case_id}/review-overview", headers=_auth()).json()
    assert overview["awaiting_information"] == 1
    assert overview["note_count"] == 1

    clarification_id = str(uuid4())
    gateway.clarifications.append({
        "id": clarification_id, "formulation_version_id": version_id,
        "question_key": "row-1-name", "question": "Confirm the submitted identity",
        "source_row_number": 1,
    })
    assert client.post(f"/cases/{case_id}/review-notes", headers=_auth(), json={
        "target_type": "clarification", "target_id": clarification_id, "body": "Source label requested.",
    }).status_code == 201
    assert client.post(f"/cases/{case_id}/review-notes", headers=_auth(), json={
        "target_type": "formulation", "target_id": version_id, "body": "Version checked against source file.",
    }).status_code == 201

    activity_response = client.get(f"/cases/{case_id}/activity", headers=_auth())
    assert activity_response.status_code == 200
    activity = activity_response.json()["entries"]
    assert {entry["kind"] for entry in activity} == {"note", "follow_up", "review_update"}
    assert any(entry["context"]["target_type"] == "finding" and entry["context"]["submitted_row_number"] == 1 for entry in activity)
    assert any(entry["context"]["target_type"] == "clarification" and entry["context"]["clarification_id"] == clarification_id for entry in activity)
    assert any(entry["context"]["target_type"] == "formulation" and entry["context"]["formulation_version_id"] == version_id for entry in activity)
    assert client.get(f"/cases/{case_id}/activity", headers=_auth("token-b")).status_code == 404

    second_run = gateway.insert_screening(USER_A, UUID(version_id), "dataset-1", "Singapore", {}, {
        "ingredient_results": [{
            "submitted_row_number": 1, "primary_finding": "information_missing", "review_required": True,
        }],
    })
    first_workspace = client.get(
        f"/formulations/{version_id}/review-workspace?screening_run_id={run['id']}", headers=_auth(),
    ).json()
    second_workspace = client.get(
        f"/formulations/{version_id}/review-workspace?screening_run_id={second_run['id']}", headers=_auth(),
    ).json()
    assert first_workspace["review_items"][0]["review_status"] == "awaiting_information"
    assert second_workspace["review_items"][0]["review_status"] == "not_reviewed"
    assert first_workspace["review_items"][0]["id"] != second_workspace["review_items"][0]["id"]
    activity = client.get(f"/cases/{case_id}/activity", headers=_auth()).json()["entries"]
    assert not any(entry["kind"] == "review_update" and entry["id"] == second_workspace["review_items"][0]["id"] for entry in activity)

    newest_version_id = str(uuid4())
    gateway.versions[newest_version_id] = {
        "id": newest_version_id, "case_id": case_id, "version_number": 2, "original_filename": "new.csv",
        "status": "clarification_required", "revision": 1, "created_at": _now(), "updated_at": _now(),
        "screening_count": 0, "raw_extraction": {}, "agent_session": None,
        "canonical_formulation": None, "product_context": None,
    }
    overview = client.get(f"/cases/{case_id}/review-overview", headers=_auth()).json()
    assert overview["current_formulation_version_id"] == newest_version_id
    assert overview["latest_screening_formulation_version_id"] == version_id
    assert overview["latest_screening_run_id"] == second_run["id"]
    assert overview["ingredients_screened"] == 1
    assert overview["attention_findings"] == 1

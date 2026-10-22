from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from backend.app.services.supabase_gateway import SupabaseGateway


class _Query:
    def __init__(self, client: "_Client", table: str):
        self.client = client
        self.table = table

    def select(self, columns: str) -> "_Query":
        self.client.selected.append((self.table, columns))
        return self

    def eq(self, *_args) -> "_Query":
        return self

    def in_(self, *_args) -> "_Query":
        return self

    def order(self, *_args, **_kwargs) -> "_Query":
        return self

    def limit(self, *_args) -> "_Query":
        return self

    def execute(self) -> SimpleNamespace:
        self.client.executed.append(self.table)
        return SimpleNamespace(data=self.client.rows.get(self.table, []))


class _Client:
    def __init__(self, rows: dict[str, list[dict]]):
        self.rows = rows
        self.selected: list[tuple[str, str]] = []
        self.executed: list[str] = []

    def table(self, name: str) -> _Query:
        return _Query(self, name)


def _gateway(client: _Client) -> SupabaseGateway:
    gateway = object.__new__(SupabaseGateway)
    gateway.client = client
    return gateway


def test_case_directory_reuses_authorized_rows_and_summary_path() -> None:
    case_id = str(uuid4())
    version_id = str(uuid4())
    run_id = str(uuid4())
    client = _Client({"cases": [{"id": case_id, "organisation_id": "org-1"}]})
    gateway = _gateway(client)
    gateway._memberships = lambda _user_id: [{"organisation_id": "org-1"}]
    gateway._list_formulations_for_authorized_case = lambda _case_id: [{"id": version_id}]
    gateway._latest_finding_count_for_authorized_version = lambda _version_id: 3
    gateway._review_overview_for_authorized_case = lambda *_args, **_kwargs: {
        "latest_screening_run_id": run_id,
        "latest_screening_formulation_version_id": version_id,
        "latest_screening_at": "2026-10-21T00:00:00Z",
        "attention_findings": 3,
        "not_reviewed": 2,
        "in_review": 1,
        "awaiting_information": 1,
        "open_follow_ups": 2,
        "unresolved_clarifications": 0,
        "last_review_activity_at": "2026-10-21T01:00:00Z",
    }
    gateway.list_formulations = lambda *_args: (_ for _ in ()).throw(AssertionError("duplicate formulation load"))
    gateway._latest_finding_count = lambda *_args: (_ for _ in ()).throw(AssertionError("duplicate authorization"))
    gateway.review_overview = lambda *_args: (_ for _ in ()).throw(AssertionError("full overview load"))

    cases = gateway.list_cases(uuid4())

    assert cases[0]["latest_finding_count"] == 3
    assert cases[0]["review_summary"]["reviewer_items_remaining"] == 4
    assert cases[0]["review_summary"]["open_follow_ups"] == 2


def test_case_directory_uses_ten_queries_for_one_case_and_one_version() -> None:
    case_id = str(uuid4())
    version_id = str(uuid4())
    run_id = str(uuid4())
    client = _Client({
        "organisation_members": [{"organisation_id": "org-1"}],
        "cases": [{"id": case_id, "organisation_id": "org-1"}],
        "formulation_versions": [{
            "id": version_id,
            "case_id": case_id,
            "version_number": 1,
            "original_filename": "pilot.csv",
            "status": "screened",
            "revision": 1,
            "created_at": "2026-10-21T00:00:00Z",
            "updated_at": "2026-10-21T00:00:00Z",
        }],
        "screening_runs": [{
            "id": run_id,
            "formulation_version_id": version_id,
            "created_at": "2026-10-21T00:00:00Z",
            "result_snapshot": {"ingredient_results": [{"primary_finding": "restriction_exceeded"}]},
        }],
        "review_items": [{
            "review_status": "not_reviewed",
            "requires_attention": True,
            "updated_at": "2026-10-21T00:30:00Z",
        }],
        "reviewer_notes": [],
        "follow_up_actions": [],
        "clarifications": [],
    })
    gateway = _gateway(client)

    cases = gateway.list_cases(uuid4())

    assert len(cases) == 1
    assert cases[0]["latest_finding_count"] == 1
    assert cases[0]["review_summary"]["reviewer_items_remaining"] == 1
    assert len(client.executed) == 10


def test_case_directory_summary_uses_narrow_columns_and_skips_context_decoration() -> None:
    case_id = str(uuid4())
    version_id = str(uuid4())
    run_id = str(uuid4())
    client = _Client({
        "screening_runs": [{
            "id": run_id,
            "formulation_version_id": version_id,
            "created_at": "2026-10-21T00:00:00Z",
        }],
        "review_items": [{
            "review_status": "not_reviewed",
            "requires_attention": True,
            "updated_at": "2026-10-21T00:30:00Z",
        }],
        "reviewer_notes": [{"created_at": "2026-10-21T00:15:00Z"}],
        "follow_up_actions": [{"status": "open", "updated_at": "2026-10-21T00:45:00Z"}],
        "clarifications": [{"id": str(uuid4())}],
    })
    gateway = _gateway(client)
    gateway._decorate_authors = lambda *_args: (_ for _ in ()).throw(AssertionError("author decoration"))
    gateway._decorate_follow_ups = lambda *_args: (_ for _ in ()).throw(AssertionError("follow-up decoration"))

    overview = gateway._review_overview_for_authorized_case(
        uuid4(),
        {"id": case_id},
        [{"id": version_id}],
        include_context_items=False,
    )

    assert overview["attention_findings"] == 1
    assert overview["not_reviewed"] == 1
    assert overview["open_follow_ups"] == 1
    assert overview["unresolved_clarifications"] == 1
    assert overview["recent_case_notes"] == []
    assert overview["open_follow_up_items"] == []
    assert ("screening_runs", "id,formulation_version_id,created_at") in client.selected
    assert ("review_items", "review_status,requires_attention,updated_at") in client.selected
    assert ("reviewer_notes", "created_at") in client.selected
    assert ("follow_up_actions", "status,updated_at") in client.selected


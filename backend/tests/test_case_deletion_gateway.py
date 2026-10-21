from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services.supabase_gateway import CaseDeletionError, SupabaseGateway


class _DeleteQuery:
    def __init__(self, client: "_DeleteClient", table: str):
        self.client = client
        self.table = table
        self.operation = "select"
        self.filters: dict[str, str] = {}

    def select(self, _columns: str):
        self.operation = "select"
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, field: str, value: str):
        self.filters[field] = value
        return self

    def limit(self, _count: int):
        return self

    def execute(self):
        self.client.events.append(f"database:{self.operation}:{self.table}")
        rows = [row for row in self.client.rows[self.table] if all(str(row.get(key)) == value for key, value in self.filters.items())]
        if self.operation == "delete" and not self.client.keep_case_after_delete:
            self.client.rows[self.table] = [row for row in self.client.rows[self.table] if row not in rows]
        return SimpleNamespace(data=rows)


class _DeleteStorageBucket:
    def __init__(self, client: "_DeleteClient"):
        self.client = client

    def remove(self, paths: list[str]):
        self.client.events.append("storage:remove")
        self.client.removed_paths = paths
        if self.client.storage_error:
            raise RuntimeError("storage unavailable")
        return paths


class _DeleteStorage:
    def __init__(self, client: "_DeleteClient"):
        self.client = client

    def from_(self, _bucket: str):
        return _DeleteStorageBucket(self.client)


class _DeleteClient:
    def __init__(self, case_id: str, *, storage_error: bool = False, keep_case_after_delete: bool = False):
        self.rows = {
            "cases": [{"id": case_id, "organisation_id": "org-1"}],
            "formulation_versions": [
                {"case_id": case_id, "source_storage_path": "org-1/case/version-1.csv"},
                {"case_id": case_id, "source_storage_path": "org-1/case/version-2.xlsx"},
                {"case_id": case_id, "source_storage_path": "org-1/case/version-1.csv"},
            ],
        }
        self.events: list[str] = []
        self.removed_paths: list[str] = []
        self.storage_error = storage_error
        self.keep_case_after_delete = keep_case_after_delete
        self.storage = _DeleteStorage(self)

    def table(self, name: str):
        return _DeleteQuery(self, name)


def _gateway(client: _DeleteClient) -> SupabaseGateway:
    gateway = object.__new__(SupabaseGateway)
    gateway.client = client
    gateway._case_row = lambda _user_id, _case_id: client.rows["cases"][0]  # type: ignore[method-assign]
    return gateway


def test_case_deletion_removes_every_unique_storage_path_before_database_records():
    case_id = str(uuid4())
    client = _DeleteClient(case_id)

    _gateway(client).delete_case(uuid4(), case_id)

    assert client.removed_paths == ["org-1/case/version-1.csv", "org-1/case/version-2.xlsx"]
    assert client.events.index("storage:remove") < client.events.index("database:delete:cases")
    assert client.rows["cases"] == []


def test_case_deletion_keeps_database_records_when_storage_cleanup_fails():
    case_id = str(uuid4())
    client = _DeleteClient(case_id, storage_error=True)

    with pytest.raises(CaseDeletionError, match="case was kept"):
        _gateway(client).delete_case(uuid4(), case_id)

    assert client.rows["cases"]
    assert "database:delete:cases" not in client.events


def test_case_deletion_verifies_that_the_database_record_was_removed():
    case_id = str(uuid4())
    client = _DeleteClient(case_id, keep_case_after_delete=True)

    with pytest.raises(CaseDeletionError, match="Case records could not be removed"):
        _gateway(client).delete_case(uuid4(), case_id)

    assert client.rows["cases"]

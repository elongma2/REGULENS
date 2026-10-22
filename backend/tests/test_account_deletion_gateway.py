from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services.supabase_gateway import (
    AccountDeletionBlockedError,
    AccountDeletionError,
    SupabaseGateway,
)


class _Query:
    def __init__(self, client, table): self.client = client; self.table = table; self.filters = {}; self.values = {}
    def select(self, _columns): return self
    def eq(self, key, value): self.filters[key] = str(value); return self
    def in_(self, key, values): self.values[key] = {str(value) for value in values}; return self
    def execute(self):
        rows = [row for row in self.client.rows.get(self.table, []) if all(str(row.get(key)) == value for key, value in self.filters.items()) and all(str(row.get(key)) in values for key, values in self.values.items())]
        return SimpleNamespace(data=rows)


class _StorageBucket:
    def __init__(self, client): self.client = client
    def remove(self, paths):
        self.client.events.append("storage")
        if self.client.storage_error: raise RuntimeError("storage unavailable")
        self.client.paths = paths


class _Storage:
    def __init__(self, client): self.client = client
    def from_(self, _bucket): return _StorageBucket(self.client)


class _Admin:
    def __init__(self, client): self.client = client
    def delete_user(self, user_id):
        self.client.events.append("auth")
        if self.client.auth_error: raise RuntimeError("auth unavailable")
        self.client.deleted_user = user_id


class _Auth:
    def __init__(self, client): self.admin = _Admin(client)


class _Rpc:
    def __init__(self, client): self.client = client
    def execute(self): self.client.events.append("database"); return SimpleNamespace(data=None)


class _Client:
    def __init__(self, *, shared=False, storage_error=False, auth_error=False):
        self.rows = {
            "organisation_members": [{"organisation_id": "org-1", "user_id": "user-1", "role": "owner"}, *([{"organisation_id": "org-1", "user_id": "user-2", "role": "member"}] if shared else [])],
            "cases": [{"id": "case-1", "organisation_id": "org-1"}],
            "formulation_versions": [{"case_id": "case-1", "source_storage_path": "org-1/case-1/version/file.csv"}],
        }
        self.events = []; self.paths = []; self.storage_error = storage_error; self.auth_error = auth_error
        self.storage = _Storage(self); self.auth = _Auth(self)
    def table(self, name): return _Query(self, name)
    def rpc(self, name, payload):
        assert name == "delete_account_domain_data" and payload["p_user_id"]
        return _Rpc(self)


def _gateway(client):
    gateway = object.__new__(SupabaseGateway); gateway.client = client
    gateway._memberships = lambda _user_id: [{"organisation_id": "org-1", "role": "owner"}]
    return gateway


def test_account_cleanup_orders_storage_database_then_auth():
    client = _Client()
    user_id = uuid4()
    _gateway(client).delete_account(user_id)
    assert client.events == ["storage", "database", "auth"]
    assert client.paths == ["org-1/case-1/version/file.csv"]
    assert client.deleted_user == str(user_id)


def test_account_cleanup_is_blocked_before_mutation_for_shared_workspace():
    client = _Client(shared=True)
    with pytest.raises(AccountDeletionBlockedError): _gateway(client).delete_account(uuid4())
    assert client.events == []


def test_account_cleanup_keeps_domain_and_auth_when_storage_fails():
    client = _Client(storage_error=True)
    with pytest.raises(AccountDeletionError, match="were kept"): _gateway(client).delete_account(uuid4())
    assert client.events == ["storage"]


def test_account_cleanup_can_retry_auth_after_domain_data_was_removed():
    client = _Client(auth_error=True); gateway = _gateway(client); user_id = uuid4()
    with pytest.raises(AccountDeletionError, match="sign-in cleanup"):
        gateway.delete_account(user_id)
    assert client.events == ["storage", "database", "auth"]

    client.auth_error = False; client.events = []
    gateway._memberships = lambda _user_id: []
    gateway.delete_account(user_id)
    assert client.events == ["auth"]

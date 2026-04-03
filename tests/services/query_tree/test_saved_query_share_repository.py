from __future__ import annotations

from app.services.query_tree.saved_query_share_models import ShareContext
from app.services.query_tree.saved_query_share_repository import SavedQueryShareRepository


class FakeSQL:
    def __init__(self, mappings_queue=None, write_returns=None):
        self._mappings_queue = list(mappings_queue or [])
        self._write_returns = list(write_returns or [])
        self.writes = []

    def execute_query_mappings(self, query: str, params):
        if self._mappings_queue:
            return self._mappings_queue.pop(0)
        return []

    def execute_write(self, query: str, params=None):
        self.writes.append((query, params))
        if self._write_returns:
            return self._write_returns.pop(0)
        return 0

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_owned_query_exists_uses_context():
    sql = FakeSQL(mappings_queue=[[{"id": "q1"}]])
    repo = SavedQueryShareRepository(ctx=ShareContext(workspace_id="ws", user_id="user"), sql=sql)

    assert repo.owned_query_exists(query_id="q1") is True


def test_fetch_acl_returns_first_row_as_dict():
    sql = FakeSQL(mappings_queue=[[{"id": "acl1", "permission": "READ"}]])
    repo = SavedQueryShareRepository(ctx=ShareContext(workspace_id="ws", user_id="user"), sql=sql)

    out = repo.fetch_acl(saved_query_id="q1", principal_type="USER", principal_id="user-2")

    assert out == {"id": "acl1", "permission": "READ"}


def test_remove_acl_returns_write_count():
    sql = FakeSQL(write_returns=[1])
    repo = SavedQueryShareRepository(ctx=ShareContext(workspace_id="ws", user_id="user"), sql=sql)

    out = repo.remove_acl(query_id="q1", principal_type="WORKSPACE", principal_id="ws")

    assert out == 1
    assert "DELETE FROM saved_query_acl" in sql.writes[0][0]

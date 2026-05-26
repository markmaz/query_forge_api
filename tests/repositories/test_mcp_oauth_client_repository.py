from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.mcp_oauth import OAuthClientRepository


class _SQL:
    def __init__(self) -> None:
        self.inserts = []
        self.writes = []
        self.queries = []
        self.rows = []

    def execute_insert(self, query, params=None):
        self.inserts.append((query, dict(params or {})))

    def execute_write(self, query, params=None):
        self.writes.append((query, dict(params or {})))
        return 3

    def execute_query_mappings(self, query, params=None):
        self.queries.append((query, dict(params or {})))
        return list(self.rows)


def test_oauth_client_repository_serializes_client_metadata_for_insert():
    sql = _SQL()
    repo = OAuthClientRepository(sql=sql)

    repo.create_client(
        payload={
            "client_id": "client-1",
            "client_secret_hash": None,
            "client_name": "ChatGPT",
            "redirect_uris": ["https://chatgpt.com/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "scope": "qf:mcp:read",
            "token_endpoint_auth_method": "none",
            "client_uri": None,
            "logo_uri": None,
            "contacts": ["admin@example.com"],
            "expires_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }
    )

    query, params = sql.inserts[0]
    assert "INSERT INTO oauth_clients" in query
    assert params["client_id"] == "client-1"
    assert params["redirect_uris"] == '["https://chatgpt.com/callback"]'
    assert params["grant_types"] == '["authorization_code"]'
    assert params["contacts"] == '["admin@example.com"]'


def test_oauth_client_repository_deletes_expired_unrevoked_clients():
    sql = _SQL()
    repo = OAuthClientRepository(sql=sql)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)

    deleted = repo.delete_expired_clients(now=now)

    assert deleted == 3
    query, params = sql.writes[0]
    assert "DELETE FROM oauth_clients" in query
    assert "expires_at < :now" in query
    assert params == {"now": now}


def test_oauth_client_repository_gets_active_client_and_decodes_json():
    sql = _SQL()
    sql.rows = [
        {
            "client_id": "client-1",
            "redirect_uris": '["https://chatgpt.com/callback"]',
            "grant_types": '["authorization_code"]',
            "response_types": '["code"]',
            "contacts": '["admin@example.com"]',
            "scope": "qf:mcp:read",
        }
    ]
    repo = OAuthClientRepository(sql=sql)

    row = repo.get_active_client(
        client_id="client-1",
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert row is not None
    assert row["redirect_uris"] == ["https://chatgpt.com/callback"]
    assert row["grant_types"] == ["authorization_code"]
    assert row["response_types"] == ["code"]
    assert row["contacts"] == ["admin@example.com"]

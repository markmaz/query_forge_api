from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.mcp_oauth import OAuthAuthorizationCodeRepository


class _SQL:
    def __init__(self, rows=None, write_count=1) -> None:
        self.inserts = []
        self.writes = []
        self.queries = []
        self.rows = list(rows or [])
        self.write_count = write_count

    def execute_insert(self, query, params=None):
        self.inserts.append((query, dict(params or {})))

    def execute_write(self, query, params=None):
        self.writes.append((query, dict(params or {})))
        return self.write_count

    def execute_query_mappings(self, query, params=None):
        self.queries.append((query, dict(params or {})))
        return list(self.rows)


def test_authorization_code_repository_inserts_code_payload():
    sql = _SQL()
    repo = OAuthAuthorizationCodeRepository(sql=sql)

    repo.create_code(
        payload={
            "code_hash": "hash-1",
            "client_id": "client-1",
            "principal_type": "user",
            "principal_id": "user-1",
            "redirect_uri": "https://chatgpt.com/callback",
            "resource": "https://mcp.query-forge.com",
            "scope": "qf:mcp:read",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "nonce": None,
            "state_hash": "state-hash",
            "expires_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        }
    )

    query, params = sql.inserts[0]
    assert "INSERT INTO oauth_authorization_codes" in query
    assert params["code_hash"] == "hash-1"
    assert params["client_id"] == "client-1"
    assert params["code_challenge_method"] == "S256"


def test_authorization_code_repository_consumes_unconsumed_code_once():
    row = {"code_hash": "hash-1", "client_id": "client-1", "consumed_at": None}
    sql = _SQL(rows=[row], write_count=1)
    repo = OAuthAuthorizationCodeRepository(sql=sql)
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)

    consumed = repo.consume_code(code_hash="hash-1", now=now)

    assert consumed == row
    assert "consumed_at IS NULL" in sql.queries[0][0]
    assert "expires_at > :now" in sql.queries[0][0]
    assert "UPDATE oauth_authorization_codes" in sql.writes[0][0]


def test_authorization_code_repository_returns_none_when_update_loses_race():
    row = {"code_hash": "hash-1", "client_id": "client-1", "consumed_at": None}
    sql = _SQL(rows=[row], write_count=0)
    repo = OAuthAuthorizationCodeRepository(sql=sql)

    consumed = repo.consume_code(
        code_hash="hash-1",
        now=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    assert consumed is None

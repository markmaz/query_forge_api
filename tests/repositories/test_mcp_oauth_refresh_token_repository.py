from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.mcp_oauth import OAuthRefreshTokenRepository


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


def test_refresh_token_repository_inserts_token_payload():
    sql = _SQL()
    repo = OAuthRefreshTokenRepository(sql=sql)

    repo.create_refresh_token(
        payload={
            "token_hash": "hash-1",
            "client_id": "client-1",
            "principal_type": "user",
            "principal_id": "user-1",
            "resource": "https://mcp.query-forge.com",
            "scope": "qf:mcp:read",
            "expires_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }
    )

    query, params = sql.inserts[0]
    assert "INSERT INTO oauth_refresh_tokens" in query
    assert params["token_hash"] == "hash-1"
    assert params["client_id"] == "client-1"


def test_refresh_token_repository_returns_only_active_tokens():
    row = {"token_hash": "hash-1", "client_id": "client-1", "revoked_at": None}
    sql = _SQL(rows=[row])
    repo = OAuthRefreshTokenRepository(sql=sql)
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)

    result = repo.get_active_refresh_token(token_hash="hash-1", now=now)

    assert result == row
    query, params = sql.queries[0]
    assert "revoked_at IS NULL" in query
    assert "rotated_at IS NULL" in query
    assert "expires_at > :now" in query
    assert params == {"token_hash": "hash-1", "now": now}


def test_refresh_token_repository_rotates_token_once():
    sql = _SQL(write_count=1)
    repo = OAuthRefreshTokenRepository(sql=sql)
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)

    rotated = repo.rotate_refresh_token(
        token_hash="old-hash",
        replacement_hash="new-hash",
        now=now,
    )

    assert rotated is True
    query, params = sql.writes[0]
    assert "UPDATE oauth_refresh_tokens" in query
    assert "rotated_at IS NULL" in query
    assert params == {
        "token_hash": "old-hash",
        "replacement_hash": "new-hash",
        "now": now,
    }


def test_refresh_token_repository_revokes_token_idempotently():
    sql = _SQL(write_count=0)
    repo = OAuthRefreshTokenRepository(sql=sql)
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)

    revoked = repo.revoke_refresh_token(token_hash="hash-1", now=now)

    assert revoked is False
    query, params = sql.writes[0]
    assert "SET revoked_at = :now" in query
    assert params == {"token_hash": "hash-1", "now": now}

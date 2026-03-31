from __future__ import annotations

from app.features.ai import nlp_api as nlp_routes
from app.services.embedding import embedding_search_service


def _auth_headers(monkeypatch):
    from app.decorators import security

    def _verify_token(token: str):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    return {"Authorization": "Bearer test-token"}


def test_extract_and_search_calls_vector(client, monkeypatch) -> None:
    def _fake_extract(workspace_id: str, domain_id: int, text: str):
        return {
            "text": text,
            "intent": "LIST",
            "entity": "course",
            "filters": [{"column_key": "is_fall", "op": "=", "value": True}],
            "debug": {},
        }

    calls = {}

    def _fake_search(self, **kwargs):
        calls.update(kwargs)
        return {"query": kwargs.get("query"), "results": []}

    monkeypatch.setattr(nlp_routes, "extract_dictionary_signals", _fake_extract)
    monkeypatch.setattr(embedding_search_service.EmbeddingSearchService, "__init__", lambda self: None)
    monkeypatch.setattr(embedding_search_service.EmbeddingSearchService, "search", _fake_search)

    headers = _auth_headers(monkeypatch)
    resp = client.post(
        "/api/v1/nlp/extract-and-search",
        headers=headers,
        json={"workspace_id": "ws1", "domain_id": 9, "text": "fall courses"},
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["nlp"]["workspace_id"] == "ws1"
    assert data["vector_request"]["domain_ids"] == [9]
    assert calls.get("domain_id") == 9
    assert calls.get("query") == "fall courses"

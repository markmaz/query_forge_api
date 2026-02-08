from __future__ import annotations

from app.services.nlp import dictionary_ner


def _stub_columns():
    return (
        dictionary_ner.ColumnInfo(
            column_name="is_fall",
            description="Fall semester indicator",
            model_table_name="course",
            source_table_name="course",
        ),
        dictionary_ner.ColumnInfo(
            column_name="is_ap",
            description="Advanced Placement course flag",
            model_table_name="course",
            source_table_name="course",
        ),
        dictionary_ner.ColumnInfo(
            column_name="is_honors",
            description="Honors course flag",
            model_table_name="course",
            source_table_name="course",
        ),
    )


def _patch_columns(monkeypatch) -> None:
    monkeypatch.setattr(dictionary_ner, "_load_domain_columns", lambda ws, did: _stub_columns())
    dictionary_ner.build_nlp.cache_clear()


def _filters(result):
    return {(item["column_key"], item["op"], item["value"]) for item in result["filters"]}


def _auth_headers(monkeypatch):
    from app.decorators import security

    def _verify_token(token: str):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    return {"Authorization": "Bearer test-token"}


def test_fall_courses_list_intent(client, monkeypatch) -> None:
    _patch_columns(monkeypatch)
    headers = _auth_headers(monkeypatch)
    resp = client.post(
        "/api/v1/nlp/extract",
        headers=headers,
        json={
            "workspace_id": "ws1",
            "domain_id": 9,
            "text": "what courses are available for students in the fall semester",
        },
    )
    assert resp.status_code == 200
    result = resp.get_json()
    assert result["entities"] == ["course"]
    assert result["intent"] == "LIST"
    assert ("is_fall", "=", True) in _filters(result)


def test_ap_courses_count_intent(client, monkeypatch) -> None:
    _patch_columns(monkeypatch)
    headers = _auth_headers(monkeypatch)
    resp = client.post(
        "/api/v1/nlp/extract",
        headers=headers,
        json={
            "workspace_id": "ws1",
            "domain_id": 9,
            "text": "how many AP courses are offered in fall",
        },
    )
    assert resp.status_code == 200
    result = resp.get_json()
    filters = _filters(result)
    assert result["intent"] == "COUNT"
    assert ("is_ap", "=", True) in filters
    assert ("is_fall", "=", True) in filters


def test_non_honors(client, monkeypatch) -> None:
    _patch_columns(monkeypatch)
    headers = _auth_headers(monkeypatch)
    resp = client.post(
        "/api/v1/nlp/extract",
        headers=headers,
        json={
            "workspace_id": "ws1",
            "domain_id": 9,
            "text": "list non honors courses",
        },
    )
    assert resp.status_code == 200
    result = resp.get_json()
    assert ("is_honors", "=", False) in _filters(result)

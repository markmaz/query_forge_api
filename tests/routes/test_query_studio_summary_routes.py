from __future__ import annotations

from typing import Dict

import app.decorators.security as security
import app.features.query_engine.query_studio_summary_api as summary_routes
from app.exceptions.llm_unavailable_error import LLMUnavailableError


def _headers(monkeypatch) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


VALID_BODY = {
    "workspace_id": "ws-1",
    "query_name": "Sales Report",
    "column_names": ["region", "revenue"],
    "rows": [{"region": "EMEA", "revenue": 100}],
}

GOOD_RESULT = {
    "narrative": "Strong EMEA performance.",
    "highlights": ["EMEA leads"],
    "comparison": None,
    "capped": False,
}


# Happy path

def test_200_with_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    monkeypatch.setattr(summary_routes, "generate_preview_summary", lambda **kw: GOOD_RESULT)
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 200
    assert resp.json["capped"] is False
    assert resp.json["narrative"] == "Strong EMEA performance."


def test_200_with_empty_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    result_empty = {**GOOD_RESULT, "capped": False}
    monkeypatch.setattr(summary_routes, "generate_preview_summary", lambda **kw: result_empty)
    body = {**VALID_BODY, "rows": []}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 200


# Validation — 422

def test_422_missing_workspace_id(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "workspace_id"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_missing_query_name(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "query_name"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_missing_column_names(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "column_names"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_missing_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {k: v for k, v in VALID_BODY.items() if k != "rows"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_non_string_workspace_id(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {**VALID_BODY, "workspace_id": 123}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


def test_422_non_array_rows(client, monkeypatch):
    headers = _headers(monkeypatch)
    body = {**VALID_BODY, "rows": "not-an-array"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"


# prompt_hint optional

def test_absent_prompt_hint_passed_as_empty_string(client, monkeypatch):
    headers = _headers(monkeypatch)
    captured = {}

    def _svc(**kw):
        captured.update(kw)
        return GOOD_RESULT

    monkeypatch.setattr(summary_routes, "generate_preview_summary", _svc)
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 200
    assert captured["prompt_hint"] == ""


def test_null_prompt_hint_passed_as_empty_string(client, monkeypatch):
    headers = _headers(monkeypatch)
    captured = {}

    def _svc(**kw):
        captured.update(kw)
        return GOOD_RESULT

    monkeypatch.setattr(summary_routes, "generate_preview_summary", _svc)
    body = {**VALID_BODY, "prompt_hint": None}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 200
    assert captured["prompt_hint"] == ""


# Error mapping

def test_503_on_llm_unavailable(client, monkeypatch):
    headers = _headers(monkeypatch)
    monkeypatch.setattr(
        summary_routes,
        "generate_preview_summary",
        lambda **kw: (_ for _ in ()).throw(LLMUnavailableError("no llm")),
    )
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 503
    assert resp.json["code"] == "llm_unavailable"


def test_500_on_unhandled_llm_failure(client, monkeypatch):
    headers = _headers(monkeypatch)
    monkeypatch.setattr(
        summary_routes,
        "generate_preview_summary",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=VALID_BODY)
    assert resp.status_code == 500
    assert resp.json["code"] == "summary_failed"


# Workspace mismatch

def test_422_workspace_mismatch(client, monkeypatch):
    headers = _headers(monkeypatch)  # X-Workspace-Id: ws-1
    body = {**VALID_BODY, "workspace_id": "ws-other"}
    resp = client.post("/api/v1/query-studio/summarize", headers=headers, json=body)
    assert resp.status_code == 422
    assert resp.json["code"] == "validation_error"
    assert "workspace_id" in resp.json["error"]

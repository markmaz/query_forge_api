from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(
        "app.decorators.security.auth_service.verify_token",
        lambda t: {"user_id": "u1", "roles": ["admin"]},
    )
    return {"Authorization": "Bearer test-token"}


def _make_llm_row(role="planner", workspace_id="ws1"):
    return {
        "id": 1,
        "workspace_id": workspace_id,
        "name": "Test LLM",
        "provider": "openai",
        "model_name": "gpt-4o",
        "role": role,
        "has_api_key": False,
        "masked_api_key": None,
        "endpoint_url": None,
        "is_active": True,
        "config_json": None,
        "created_at": "",
        "updated_at": "",
    }


def test_get_llm_roles(client, auth_headers):
    resp = client.get("/api/v1/llm-roles", headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, list)
    assert any(r["value"] == "planner" for r in data)
    assert any(r["value"] == "ner" for r in data)
    assert any(r["value"] == "flowforge_rule_drafting" for r in data)


def test_get_llm_providers(client, auth_headers):
    resp = client.get("/api/v1/llm-providers", headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, list)
    assert any(p["value"] == "openai" for p in data)
    assert any(p["value"] == "anthropic" for p in data)


def test_list_workspace_llms(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_all_for_workspace.return_value = [_make_llm_row()]
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.get("/api/v1/workspaces/ws1/llms", headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data) == 1
    assert "api_key_encrypted" not in str(data)
    assert data[0]["role"] == "planner"


def test_create_workspace_llm_validates_role(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.create_llm.side_effect = ValueError("Invalid role 'bad_role'")
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.post(
            "/api/v1/workspaces/ws1/llms",
            headers={**auth_headers, "Content-Type": "application/json"},
            data=json.dumps({
                "name": "Test",
                "provider": "openai",
                "model_name": "gpt-4o",
                "role": "bad_role",
            }),
        )
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data


def test_test_connection_endpoint(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_by_id.return_value = _make_llm_row()
    mock_svc.test_connection.return_value = {"success": True, "message": "Connected"}
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.post(
            "/api/v1/workspaces/ws1/llms/1/test",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
    assert "message" in data


def test_test_connection_cross_workspace_returns_404(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_by_id.return_value = _make_llm_row(workspace_id="other-ws")
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.post(
            "/api/v1/workspaces/ws1/llms/1/test",
            headers=auth_headers,
        )
    assert resp.status_code == 404


def test_delete_workspace_llm(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_by_id.return_value = _make_llm_row()
    mock_svc.delete_llm.return_value = None
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.delete(
            "/api/v1/workspaces/ws1/llms/1",
            headers=auth_headers,
        )
    assert resp.status_code == 200


def test_delete_cross_workspace_returns_404(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_by_id.return_value = _make_llm_row(workspace_id="other-ws")
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.delete(
            "/api/v1/workspaces/ws1/llms/1",
            headers=auth_headers,
        )
    assert resp.status_code == 404


def test_put_workspace_llm(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_by_id.return_value = _make_llm_row()
    mock_svc.update_llm.return_value = {**_make_llm_row(), "name": "Updated"}
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.put(
            "/api/v1/workspaces/ws1/llms/1",
            headers={**auth_headers, "Content-Type": "application/json"},
            data=json.dumps({"name": "Updated"}),
        )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["name"] == "Updated"


def test_put_cross_workspace_returns_404(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_by_id.return_value = _make_llm_row(workspace_id="other-ws")
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.put(
            "/api/v1/workspaces/ws1/llms/1",
            headers={**auth_headers, "Content-Type": "application/json"},
            data=json.dumps({"name": "Hacked"}),
        )
    assert resp.status_code == 404


def test_put_not_found_returns_404(client, auth_headers):
    mock_svc = MagicMock()
    mock_svc.get_by_id.return_value = None
    with patch("app.features.workspaces.workspace_llm_api.WorkspaceLLMService", return_value=mock_svc):
        resp = client.put(
            "/api/v1/workspaces/ws1/llms/999",
            headers={**auth_headers, "Content-Type": "application/json"},
            data=json.dumps({"name": "Ghost"}),
        )
    assert resp.status_code == 404


def test_list_workspace_llms_requires_auth(client):
    resp = client.get("/api/v1/workspaces/ws1/llms")
    assert resp.status_code in (401, 403)

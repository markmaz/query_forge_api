from __future__ import annotations

from starlette.testclient import TestClient

from mcp_server.config import MCPSettings
from mcp_server import server
from mcp_server.server import create_streamable_http_app


def test_streamable_http_app_exposes_protected_resource_metadata():
    settings = MCPSettings(
        resource_url="https://mcp.query-forge.com",
        authorization_server_url="https://api.query-forge.com",
        oauth_scopes_supported=("qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"),
    )
    app = create_streamable_http_app(settings=settings)

    response = TestClient(app).get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "https://mcp.query-forge.com"
    assert payload["authorization_servers"] == ["https://api.query-forge.com"]
    assert payload["scopes_supported"] == ["qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"]
    assert payload["resource_documentation"] == "https://api.query-forge.com/docs/mcp"


def test_streamable_http_app_exposes_public_healthz():
    settings = MCPSettings(server_version="0.3.331")
    app = create_streamable_http_app(settings=settings)

    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "queryforge-mcp",
        "version": "0.3.331",
    }


def test_main_runs_wrapped_asgi_app(monkeypatch):
    settings = MCPSettings(host="127.0.0.1", port=8123, debug=True)
    app_marker = object()
    captured = {}

    monkeypatch.setattr(server.MCPSettings, "from_env", lambda: settings)
    monkeypatch.setattr(server, "create_streamable_http_app", lambda *, settings: app_marker)
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **kwargs: captured.update({"app": app, **kwargs}))

    server.main()

    assert captured == {
        "app": app_marker,
        "host": "127.0.0.1",
        "port": 8123,
        "log_level": "debug",
    }

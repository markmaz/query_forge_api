from __future__ import annotations

from app.adapters.databricks_workspace_token_provider import DatabricksWorkspaceTokenProvider


def test_provider_accepts_workspace_id_keyword(monkeypatch) -> None:
    captured = {}

    def _fake_base_init(self, name, token_url, client_id, client_secret, scope="all-apis"):
        captured.update(
            {
                "name": name,
                "token_url": token_url,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            }
        )

    monkeypatch.setattr(
        "app.adapters.databricks_workspace_token_provider.BaseForgeTokenManager.__init__",
        _fake_base_init,
    )

    DatabricksWorkspaceTokenProvider(
        workspace_host="https://adb-1.azuredatabricks.net",
        workspace_id="ws-1",
        client_id="client-1",
        client_secret="secret-1",
    )

    assert captured["name"] == "DATABRICKS_WORKSPACE_TOKEN_MANAGER"
    assert captured["token_url"] == "https://adb-1.azuredatabricks.net/oidc/v1/token"
    assert captured["client_id"] == "client-1"
    assert captured["client_secret"] == "secret-1"
    assert captured["scope"] == "all-apis"

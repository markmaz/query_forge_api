from __future__ import annotations


def test_authorization_server_metadata_is_served_from_well_known(client, monkeypatch):
    monkeypatch.setenv("OAUTH_ISSUER_URL", "https://api.query-forge.com/")
    monkeypatch.setenv("OAUTH_ALLOWED_CODE_CHALLENGE_METHODS", "S256")
    monkeypatch.setenv("OAUTH_ENABLE_DYNAMIC_CLIENT_REGISTRATION", "true")
    monkeypatch.setenv("OAUTH_ENABLE_REFRESH_TOKENS", "true")

    response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["issuer"] == "https://api.query-forge.com"
    assert payload["authorization_endpoint"] == "https://api.query-forge.com/oauth/authorize"
    assert payload["token_endpoint"] == "https://api.query-forge.com/oauth/token"
    assert payload["registration_endpoint"] == "https://api.query-forge.com/oauth/register"
    assert payload["revocation_endpoint"] == "https://api.query-forge.com/oauth/revoke"
    assert payload["response_types_supported"] == ["code"]
    assert payload["grant_types_supported"] == ["authorization_code", "refresh_token", "client_credentials"]
    assert payload["code_challenge_methods_supported"] == ["S256"]
    assert payload["scopes_supported"] == ["qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"]


def test_authorization_server_metadata_is_available_from_documented_api_route(client, monkeypatch):
    monkeypatch.setenv("OAUTH_ISSUER_URL", "http://localhost:5000")

    response = client.get("/api/v1/mcp-oauth/authorization-server-metadata")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["issuer"] == "http://localhost:5000"
    assert payload["authorization_endpoint"] == "http://localhost:5000/oauth/authorize"


def test_oauth_register_endpoint_creates_dynamic_client(client, monkeypatch):
    monkeypatch.setenv("OAUTH_ALLOWED_REDIRECT_HOSTS", "chatgpt.com")
    monkeypatch.setenv("OAUTH_ENABLE_DYNAMIC_CLIENT_REGISTRATION", "true")

    class _Service:
        def register_client(self, payload):
            assert payload["redirect_uris"] == ["https://chatgpt.com/callback"]
            return {
                "client_id": "client-123",
                "client_id_issued_at": 1_777_000_000,
                "redirect_uris": ["https://chatgpt.com/callback"],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "scope": "qf:mcp:read",
                "token_endpoint_auth_method": "none",
            }

    monkeypatch.setattr(
        "app.features.mcp_oauth.routes.DynamicClientRegistrationService",
        lambda: _Service(),
    )

    response = client.post(
        "/oauth/register",
        json={
            "client_name": "ChatGPT",
            "redirect_uris": ["https://chatgpt.com/callback"],
        },
    )

    assert response.status_code == 201
    assert response.get_json()["client_id"] == "client-123"


def test_oauth_register_endpoint_returns_validation_errors(client, monkeypatch):
    monkeypatch.setenv("OAUTH_ALLOWED_REDIRECT_HOSTS", "chatgpt.com")

    response = client.post(
        "/oauth/register",
        json={
            "client_name": "Bad Client",
            "redirect_uris": ["https://evil.example/callback"],
        },
    )

    assert response.status_code == 400
    assert "redirect_uri host is not allowed" in response.get_json()["error"]


def test_oauth_authorize_get_renders_login_and_consent_form(client, monkeypatch):
    class _Service:
        def validate_authorization_request(self, payload):
            assert payload["client_id"] == "client-123"
            return type(
                "RequestContext",
                (),
                {
                    "client_id": "client-123",
                    "client_name": "ChatGPT",
                    "redirect_uri": "https://chatgpt.com/callback",
                    "resource": "https://mcp.query-forge.com",
                    "scopes": ["qf:mcp:read"],
                    "state": "state-1",
                    "code_challenge": "challenge",
                    "code_challenge_method": "S256",
                },
            )()

    monkeypatch.setattr(
        "app.features.mcp_oauth.routes.AuthorizationCodeService",
        lambda: _Service(),
    )

    response = client.get(
        "/oauth/authorize",
        query_string={
            "response_type": "code",
            "client_id": "client-123",
            "redirect_uri": "https://chatgpt.com/callback",
            "resource": "https://mcp.query-forge.com",
            "scope": "qf:mcp:read",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "state": "state-1",
        },
    )

    assert response.status_code == 200
    assert response.content_type == "text/html; charset=utf-8"
    assert "img-src 'self'" in response.headers["Content-Security-Policy"]
    assert "style-src 'unsafe-inline'" in response.headers["Content-Security-Policy"]
    assert "form-action 'self' https://chatgpt.com" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert b"Connect governed context." in response.data
    assert b'/static/images/qf_logo_mark.png' in response.data
    assert b"Allow MCP access" in response.data
    assert b"ChatGPT" in response.data
    assert b"qf:mcp:read" in response.data


def test_oauth_authorize_post_redirects_with_authorization_code(client, monkeypatch):
    class _Service:
        def authorize_with_password(self, payload):
            assert payload["username"] == "user@example.com"
            assert payload["consent"] == "approve"
            return "https://chatgpt.com/callback?code=code-1&state=state-1"

    monkeypatch.setattr(
        "app.features.mcp_oauth.routes.AuthorizationCodeService",
        lambda: _Service(),
    )

    response = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "client-123",
            "redirect_uri": "https://chatgpt.com/callback",
            "resource": "https://mcp.query-forge.com",
            "scope": "qf:mcp:read",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "state": "state-1",
            "username": "user@example.com",
            "password": "secret",
            "consent": "approve",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://chatgpt.com/callback?code=code-1&state=state-1"


def test_oauth_token_endpoint_exchanges_authorization_code(client, monkeypatch):
    class _Service:
        def issue_token(self, payload):
            assert payload["grant_type"] == "authorization_code"
            assert payload["client_id"] == "client-123"
            assert payload["code_verifier"] == "verifier-1"
            return {
                "access_token": "access-1",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "qf:mcp:read",
                "refresh_token": "refresh-1",
            }

    monkeypatch.setattr(
        "app.features.mcp_oauth.routes.OAuthTokenService",
        lambda: _Service(),
    )

    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "client-123",
            "code": "code-1",
            "redirect_uri": "https://chatgpt.com/callback",
            "resource": "https://mcp.query-forge.com",
            "code_verifier": "verifier-1",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["access_token"] == "access-1"
    assert payload["refresh_token"] == "refresh-1"


def test_oauth_token_endpoint_accepts_basic_client_auth(client, monkeypatch):
    class _Service:
        def issue_token(self, payload):
            assert payload["client_id"] == "client-basic"
            assert payload["client_secret"] == "secret-1"
            return {
                "access_token": "access-1",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "qf:mcp:read",
            }

    monkeypatch.setattr(
        "app.features.mcp_oauth.routes.OAuthTokenService",
        lambda: _Service(),
    )

    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": "refresh-1",
        },
        auth=("client-basic", "secret-1"),
    )

    assert response.status_code == 200
    assert response.get_json()["access_token"] == "access-1"


def test_oauth_token_endpoint_supports_client_credentials_for_app_principals(client, monkeypatch):
    class _Service:
        def issue_token(self, payload):
            assert payload["grant_type"] == "client_credentials"
            assert payload["client_id"] == "app-client"
            assert payload["client_secret"] == "app-secret"
            return {
                "access_token": "app-access-1",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "qf:mcp:read qf:mcp:plan",
            }

    monkeypatch.setattr(
        "app.features.mcp_oauth.routes.OAuthTokenService",
        lambda: _Service(),
    )

    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "scope": "qf:mcp:read qf:mcp:plan",
        },
        auth=("app-client", "app-secret"),
    )

    assert response.status_code == 200
    assert response.get_json()["access_token"] == "app-access-1"


def test_oauth_revoke_endpoint_revokes_refresh_token(client, monkeypatch):
    class _Service:
        def revoke_token(self, payload):
            assert payload["token"] == "refresh-1"
            assert payload["token_type_hint"] == "refresh_token"
            return {"revoked": True}

    monkeypatch.setattr(
        "app.features.mcp_oauth.routes.OAuthTokenService",
        lambda: _Service(),
    )

    response = client.post(
        "/oauth/revoke",
        json={
            "token": "refresh-1",
            "token_type_hint": "refresh_token",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"revoked": True}

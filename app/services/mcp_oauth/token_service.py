from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets
from typing import Any, Callable, Mapping
import uuid

from app.config.mcp_oauth_config import MCP_OAUTH_SCOPES, MCPOAuthConfig, load_mcp_oauth_config
from app.exceptions.forge_error import ForgeError
from app.repositories.mcp_oauth import MCPAppClientRepository, OAuthClientRepository, OAuthRefreshTokenRepository
from app.services.auth_service import AuthService
from app.services.mcp_oauth.authorization_code_service import AuthorizationCodeService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OAuthTokenService:
    def __init__(
        self,
        *,
        config_loader: Callable[[], MCPOAuthConfig] = load_mcp_oauth_config,
        client_repository: OAuthClientRepository | None = None,
        app_client_repository: MCPAppClientRepository | None = None,
        authorization_code_service: AuthorizationCodeService | None = None,
        refresh_token_repository: OAuthRefreshTokenRepository | None = None,
        auth_service: AuthService | None = None,
        refresh_token_generator: Callable[[], str] | None = None,
        jti_generator: Callable[[], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._client_repository = client_repository or OAuthClientRepository()
        self._app_client_repository = app_client_repository or MCPAppClientRepository()
        self._authorization_code_service = authorization_code_service or AuthorizationCodeService()
        self._refresh_token_repository = refresh_token_repository or OAuthRefreshTokenRepository()
        self._auth_service = auth_service or AuthService()
        self._refresh_token_generator = refresh_token_generator or (lambda: f"qf_refresh_{secrets.token_urlsafe(40)}")
        self._jti_generator = jti_generator or (lambda: uuid.uuid4().hex)
        self._now_provider = now_provider or _utc_now

    def issue_token(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        grant_type = str(payload.get("grant_type") or "").strip()
        if grant_type == "authorization_code":
            return self._exchange_authorization_code(payload)
        if grant_type == "refresh_token":
            return self._rotate_refresh_token(payload)
        if grant_type == "client_credentials":
            return self._exchange_client_credentials(payload)
        raise ForgeError("Unsupported grant_type", status_code=400)

    def revoke_token(self, payload: Mapping[str, Any]) -> dict[str, bool]:
        token = str(payload.get("token") or "").strip()
        if not token:
            raise ForgeError("token is required", status_code=400)

        # RFC 7009 revocation is intentionally idempotent. Access tokens are short-lived
        # JWTs in v1; durable revocation is enforced for persisted refresh tokens.
        self._refresh_token_repository.revoke_refresh_token(
            token_hash=self._sha256(token),
            now=self._now_provider(),
        )
        return {"revoked": True}

    def _exchange_authorization_code(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        config = self._config_loader()
        now = self._now_provider()
        client = self._load_and_authenticate_client(payload=payload, now=now, required_grant="authorization_code")

        code = str(payload.get("code") or "").strip()
        if not code:
            raise ForgeError("code is required", status_code=400)

        code_row = self._authorization_code_service.consume_authorization_code(code)
        if not code_row:
            raise ForgeError("Invalid or expired authorization code", status_code=400)

        if str(code_row.get("client_id") or "") != str(client.get("client_id") or ""):
            raise ForgeError("Authorization code client mismatch", status_code=400)

        redirect_uri = str(payload.get("redirect_uri") or "").strip()
        if redirect_uri != str(code_row.get("redirect_uri") or "").strip():
            raise ForgeError("redirect_uri does not match authorization code", status_code=400)

        resource = str(payload.get("resource") or code_row.get("resource") or "").strip().rstrip("/")
        if resource != str(code_row.get("resource") or "").strip().rstrip("/"):
            raise ForgeError("resource does not match authorization code", status_code=400)
        if resource != config.mcp_resource_url.rstrip("/"):
            raise ForgeError("resource does not match QueryForge MCP resource", status_code=400)

        self._verify_pkce(payload=payload, code_row=code_row)
        return self._build_token_response(
            client_id=str(client["client_id"]),
            principal_type=str(code_row.get("principal_type") or "user"),
            principal_id=str(code_row.get("principal_id") or ""),
            resource=resource,
            scope=str(code_row.get("scope") or ""),
            issue_refresh=config.oauth_enable_refresh_tokens and self._client_allows_grant(client, "refresh_token"),
            now=now,
            config=config,
        )

    def _rotate_refresh_token(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        config = self._config_loader()
        if not config.oauth_enable_refresh_tokens:
            raise ForgeError("refresh_token grant is disabled", status_code=400)

        now = self._now_provider()
        client = self._load_and_authenticate_client(payload=payload, now=now, required_grant="refresh_token")
        refresh_token = str(payload.get("refresh_token") or "").strip()
        if not refresh_token:
            raise ForgeError("refresh_token is required", status_code=400)

        token_hash = self._sha256(refresh_token)
        refresh_row = self._refresh_token_repository.get_active_refresh_token(token_hash=token_hash, now=now)
        if not refresh_row:
            raise ForgeError("Invalid or expired refresh token", status_code=401)
        if str(refresh_row.get("client_id") or "") != str(client.get("client_id") or ""):
            raise ForgeError("Refresh token client mismatch", status_code=401)

        new_refresh_token = self._refresh_token_generator()
        new_hash = self._sha256(new_refresh_token)
        if not self._refresh_token_repository.rotate_refresh_token(
            token_hash=token_hash,
            replacement_hash=new_hash,
            now=now,
        ):
            raise ForgeError("Refresh token already used", status_code=401)

        response = self._issue_access_token_response(
            client_id=str(client["client_id"]),
            principal_type=str(refresh_row.get("principal_type") or "user"),
            principal_id=str(refresh_row.get("principal_id") or ""),
            resource=str(refresh_row.get("resource") or config.mcp_resource_url).rstrip("/"),
            scope=str(refresh_row.get("scope") or ""),
            now=now,
            config=config,
        )
        self._persist_refresh_token(
            token=new_refresh_token,
            client_id=str(client["client_id"]),
            principal_type=str(refresh_row.get("principal_type") or "user"),
            principal_id=str(refresh_row.get("principal_id") or ""),
            resource=str(refresh_row.get("resource") or config.mcp_resource_url).rstrip("/"),
            scope=str(refresh_row.get("scope") or ""),
            now=now,
            config=config,
        )
        response["refresh_token"] = new_refresh_token
        return response

    def _exchange_client_credentials(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        config = self._config_loader()
        if not config.oauth_enable_app_client_auth:
            raise ForgeError("client_credentials grant is disabled", status_code=400)

        now = self._now_provider()
        client_id = str(payload.get("client_id") or "").strip()
        client_secret = str(payload.get("client_secret") or "").strip()
        if not client_id or not client_secret:
            raise ForgeError("client_id and client_secret are required", status_code=400)

        app_client = self._app_client_repository.get_active_client(client_id=client_id, now=now)
        if not app_client:
            raise ForgeError("Unknown or inactive MCP app client", status_code=401)
        expected_hash = str(app_client.get("client_secret_hash") or "").strip()
        if not expected_hash or not hmac.compare_digest(expected_hash, self._sha256(client_secret)):
            raise ForgeError("Invalid client authentication", status_code=401)

        resource = str(payload.get("resource") or config.mcp_resource_url).strip().rstrip("/")
        if resource != config.mcp_resource_url.rstrip("/"):
            raise ForgeError("resource does not match QueryForge MCP resource", status_code=400)

        scope = self._validate_requested_scope(payload.get("scope"))
        self._app_client_repository.touch_last_used(client_id=client_id, now=now)
        return self._issue_access_token_response(
            client_id=client_id,
            principal_type="app",
            principal_id=client_id,
            resource=resource,
            scope=scope,
            now=now,
            config=config,
        )

    def _build_token_response(
        self,
        *,
        client_id: str,
        principal_type: str,
        principal_id: str,
        resource: str,
        scope: str,
        issue_refresh: bool,
        now: datetime,
        config: MCPOAuthConfig,
    ) -> dict[str, Any]:
        response = self._issue_access_token_response(
            client_id=client_id,
            principal_type=principal_type,
            principal_id=principal_id,
            resource=resource,
            scope=scope,
            now=now,
            config=config,
        )
        if issue_refresh:
            refresh_token = self._refresh_token_generator()
            self._persist_refresh_token(
                token=refresh_token,
                client_id=client_id,
                principal_type=principal_type,
                principal_id=principal_id,
                resource=resource,
                scope=scope,
                now=now,
                config=config,
            )
            response["refresh_token"] = refresh_token
        return response

    def _issue_access_token_response(
        self,
        *,
        client_id: str,
        principal_type: str,
        principal_id: str,
        resource: str,
        scope: str,
        now: datetime,
        config: MCPOAuthConfig,
    ) -> dict[str, Any]:
        if not principal_id:
            raise ForgeError("Unable to resolve token principal", status_code=401)
        token = self._auth_service._encode(
            {
                "iss": config.oauth_issuer_url,
                "aud": resource,
                "sub": principal_id,
                "typ": "mcp_access",
                "jti": self._jti_generator(),
                "iat": int(now.timestamp()),
                "exp": now + timedelta(seconds=config.oauth_access_token_ttl_seconds),
                "client_id": client_id,
                "principal_type": principal_type,
                "scope": scope,
                "resource": resource,
            }
        )
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": config.oauth_access_token_ttl_seconds,
            "scope": scope,
        }

    def _persist_refresh_token(
        self,
        *,
        token: str,
        client_id: str,
        principal_type: str,
        principal_id: str,
        resource: str,
        scope: str,
        now: datetime,
        config: MCPOAuthConfig,
    ) -> None:
        self._refresh_token_repository.create_refresh_token(
            payload={
                "token_hash": self._sha256(token),
                "client_id": client_id,
                "principal_type": principal_type,
                "principal_id": principal_id,
                "resource": resource,
                "scope": scope,
                "expires_at": now + timedelta(seconds=config.oauth_refresh_token_ttl_seconds),
            }
        )

    def _load_and_authenticate_client(
        self,
        *,
        payload: Mapping[str, Any],
        now: datetime,
        required_grant: str,
    ) -> dict[str, Any]:
        client_id = str(payload.get("client_id") or "").strip()
        if not client_id:
            raise ForgeError("client_id is required", status_code=400)
        client = self._client_repository.get_active_client(client_id=client_id, now=now)
        if not client:
            raise ForgeError("Unknown or inactive OAuth client", status_code=401)
        if not self._client_allows_grant(client, required_grant):
            raise ForgeError("OAuth client is not allowed to use this grant_type", status_code=400)
        self._authenticate_client_secret(payload=payload, client=client)
        return client

    def _authenticate_client_secret(self, *, payload: Mapping[str, Any], client: Mapping[str, Any]) -> None:
        method = str(client.get("token_endpoint_auth_method") or "none").strip()
        if method == "none":
            return

        expected_hash = str(client.get("client_secret_hash") or "").strip()
        supplied_secret = str(payload.get("client_secret") or "").strip()
        if not expected_hash or not supplied_secret:
            raise ForgeError("Invalid client authentication", status_code=401)
        supplied_hash = self._sha256(supplied_secret)
        if not hmac.compare_digest(expected_hash, supplied_hash):
            raise ForgeError("Invalid client authentication", status_code=401)

    def _verify_pkce(self, *, payload: Mapping[str, Any], code_row: Mapping[str, Any]) -> None:
        verifier = str(payload.get("code_verifier") or "").strip()
        if not verifier:
            raise ForgeError("code_verifier is required", status_code=400)

        challenge = str(code_row.get("code_challenge") or "").strip()
        method = str(code_row.get("code_challenge_method") or "plain").strip()
        if method == "S256":
            digest = hashlib.sha256(verifier.encode("utf-8")).digest()
            expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        elif method == "plain":
            expected = verifier
        else:
            raise ForgeError("Unsupported code_challenge_method", status_code=400)

        if not hmac.compare_digest(challenge, expected):
            raise ForgeError("Invalid code_verifier", status_code=400)

    def _client_allows_grant(self, client: Mapping[str, Any], grant_type: str) -> bool:
        grant_types = client.get("grant_types") or ["authorization_code"]
        return str(grant_type) in {str(item) for item in grant_types}

    def _validate_requested_scope(self, value: Any) -> str:
        requested = [scope for scope in str(value or "qf:mcp:read qf:mcp:plan").split(" ") if scope]
        supported = set(MCP_OAUTH_SCOPES)
        unsupported = [scope for scope in requested if scope not in supported]
        if unsupported:
            raise ForgeError("scope contains unsupported values", status_code=400, details={"unsupported": unsupported})
        return " ".join(dict.fromkeys(requested))

    def _sha256(self, value: str) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


__all__ = ["OAuthTokenService"]

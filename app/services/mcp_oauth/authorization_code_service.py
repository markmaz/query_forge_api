from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

from app.config.mcp_oauth_config import MCP_OAUTH_SCOPES, MCPOAuthConfig, load_mcp_oauth_config
from app.exceptions.forge_error import ForgeError
from app.repositories.mcp_oauth import OAuthAuthorizationCodeRepository, OAuthClientRepository
from app.services.auth import TotpService
from app.services.auth_service import AuthService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuthorizationRequestContext:
    client_id: str
    client_name: str | None
    redirect_uri: str
    resource: str
    scopes: list[str]
    state: str | None
    code_challenge: str
    code_challenge_method: str
    nonce: str | None = None


class AuthorizationCodeService:
    def __init__(
        self,
        *,
        config_loader: Callable[[], MCPOAuthConfig] = load_mcp_oauth_config,
        client_repository: OAuthClientRepository | None = None,
        code_repository: OAuthAuthorizationCodeRepository | None = None,
        auth_service: AuthService | None = None,
        totp_service: TotpService | None = None,
        code_generator: Callable[[], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._client_repository = client_repository or OAuthClientRepository()
        self._code_repository = code_repository or OAuthAuthorizationCodeRepository()
        self._auth_service = auth_service or AuthService()
        self._totp_service = totp_service or TotpService()
        self._code_generator = code_generator or (lambda: f"qf_auth_{secrets.token_urlsafe(32)}")
        self._now_provider = now_provider or _utc_now

    def validate_authorization_request(self, payload: Mapping[str, Any]) -> AuthorizationRequestContext:
        config = self._config_loader()
        if str(payload.get("response_type") or "").strip() != "code":
            raise ForgeError("response_type must be code", status_code=400)

        client_id = str(payload.get("client_id") or "").strip()
        if not client_id:
            raise ForgeError("client_id is required", status_code=400)

        now = self._now_provider()
        client = self._client_repository.get_active_client(client_id=client_id, now=now)
        if not client:
            raise ForgeError("Unknown or inactive OAuth client", status_code=400)

        redirect_uri = str(payload.get("redirect_uri") or "").strip()
        registered_redirects = {str(uri or "").strip() for uri in client.get("redirect_uris") or []}
        if redirect_uri not in registered_redirects:
            raise ForgeError("redirect_uri is not registered for this client", status_code=400)

        resource = str(payload.get("resource") or config.mcp_resource_url).strip().rstrip("/")
        if resource != config.mcp_resource_url.rstrip("/"):
            raise ForgeError("resource does not match QueryForge MCP resource", status_code=400)

        code_challenge = str(payload.get("code_challenge") or "").strip()
        if config.oauth_require_pkce and not code_challenge:
            raise ForgeError("code_challenge is required", status_code=400)

        method = str(payload.get("code_challenge_method") or "plain").strip()
        if method not in set(config.oauth_allowed_code_challenge_methods):
            raise ForgeError("Unsupported code_challenge_method", status_code=400)

        scopes = self._validate_scopes(payload.get("scope"), client_scope=client.get("scope"))
        return AuthorizationRequestContext(
            client_id=client_id,
            client_name=str(client.get("client_name") or "").strip() or None,
            redirect_uri=redirect_uri,
            resource=resource,
            scopes=scopes,
            state=str(payload.get("state") or "").strip() or None,
            code_challenge=code_challenge,
            code_challenge_method=method,
            nonce=str(payload.get("nonce") or "").strip() or None,
        )

    def authorize_with_password(self, payload: Mapping[str, Any]) -> str:
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not username or not password:
            raise ForgeError("username and password are required", status_code=400)
        if str(payload.get("consent") or "").strip().lower() not in {"approve", "approved", "true", "1", "yes"}:
            raise ForgeError("OAuth consent is required", status_code=400)

        user = self._auth_service.non_interactive_authentication(username, password)
        user_id = str(getattr(user, "user_id", "") or "").strip()
        if user_id == "":
            raise ForgeError("Unable to resolve authenticated user", status_code=401)

        if self._totp_service.is_totp_enabled(user_id):
            code = str(payload.get("totp_code") or "").strip()
            if not code:
                raise ForgeError("totp_code is required", status_code=401)
            if not self._totp_service.verify_totp_code(user_id, code):
                raise ForgeError("Invalid TOTP code", status_code=401)

        return self.issue_authorization_code(user_id=user_id, request_payload=payload)

    def issue_authorization_code(self, *, user_id: str, request_payload: Mapping[str, Any]) -> str:
        request_ctx = self.validate_authorization_request(request_payload)
        now = self._now_provider()
        config = self._config_loader()
        code = self._code_generator()
        self._code_repository.create_code(
            payload={
                "code_hash": self._sha256(code),
                "client_id": request_ctx.client_id,
                "principal_type": "user",
                "principal_id": str(user_id),
                "redirect_uri": request_ctx.redirect_uri,
                "resource": request_ctx.resource,
                "scope": " ".join(request_ctx.scopes),
                "code_challenge": request_ctx.code_challenge,
                "code_challenge_method": request_ctx.code_challenge_method,
                "nonce": request_ctx.nonce,
                "state_hash": self._sha256(request_ctx.state) if request_ctx.state else None,
                "expires_at": now + timedelta(seconds=config.oauth_auth_code_ttl_seconds),
            }
        )
        query: dict[str, str] = {
            "code": code,
        }
        if request_ctx.state:
            query["state"] = request_ctx.state
        query["resource"] = request_ctx.resource
        return f"{request_ctx.redirect_uri}?{urlencode(query)}"

    def consume_authorization_code(self, code: str) -> dict[str, Any] | None:
        return self._code_repository.consume_code(
            code_hash=self._sha256(str(code or "").strip()),
            now=self._now_provider(),
        )

    def _validate_scopes(self, raw_scope: Any, *, client_scope: Any) -> list[str]:
        requested = [scope for scope in str(raw_scope or client_scope or "qf:mcp:read qf:mcp:plan").split(" ") if scope]
        supported = set(MCP_OAUTH_SCOPES)
        unsupported = [scope for scope in requested if scope not in supported]
        if unsupported:
            raise ForgeError("scope contains unsupported values", status_code=400, details={"unsupported": unsupported})

        client_allowed = {scope for scope in str(client_scope or "").split(" ") if scope}
        if client_allowed:
            outside_client = [scope for scope in requested if scope not in client_allowed]
            if outside_client:
                raise ForgeError(
                    "scope exceeds registered client scope",
                    status_code=400,
                    details={"unsupported": outside_client},
                )
        return list(dict.fromkeys(requested))

    def _sha256(self, value: str | None) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


__all__ = ["AuthorizationCodeService", "AuthorizationRequestContext"]

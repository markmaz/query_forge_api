from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import secrets
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from app.config.mcp_oauth_config import MCP_OAUTH_SCOPES, MCPOAuthConfig, load_mcp_oauth_config
from app.exceptions.forge_error import ForgeError
from app.repositories.mcp_oauth import OAuthClientRepository

SUPPORTED_RESPONSE_TYPES = ("code",)
BASE_SUPPORTED_GRANT_TYPES = ("authorization_code", "client_credentials")
SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS = (
    "none",
    "client_secret_basic",
    "client_secret_post",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | int | float) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp())
    return int(value)


class DynamicClientRegistrationService:
    def __init__(
        self,
        *,
        config_loader: Callable[[], MCPOAuthConfig] = load_mcp_oauth_config,
        repository: OAuthClientRepository | None = None,
        id_generator: Callable[[], str] | None = None,
        secret_generator: Callable[[], str] | None = None,
        now_provider: Callable[[], datetime | int | float] | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._repository = repository or OAuthClientRepository()
        self._id_generator = id_generator or (lambda: f"qf_mcp_{secrets.token_urlsafe(24)}")
        self._secret_generator = secret_generator or (lambda: secrets.token_urlsafe(40))
        self._now_provider = now_provider or _utc_now

    def register_client(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        config = self._config_loader()
        if not config.oauth_enable_dynamic_client_registration:
            raise ForgeError("Dynamic client registration is disabled", status_code=404)

        now_raw = self._now_provider()
        issued_at = _timestamp(now_raw)
        now = now_raw if isinstance(now_raw, datetime) else datetime.fromtimestamp(issued_at, tz=timezone.utc)
        redirect_uris = self._validate_redirect_uris(payload.get("redirect_uris"), config)
        grant_types = self._validate_grant_types(payload.get("grant_types"), config)
        response_types = self._validate_response_types(payload.get("response_types"))
        scope = self._validate_scope(payload.get("scope"))
        auth_method = self._validate_auth_method(payload.get("token_endpoint_auth_method"))
        contacts = self._validate_optional_string_list(payload.get("contacts"), "contacts")

        client_id = self._id_generator()
        client_secret = self._secret_generator() if auth_method != "none" else None
        expires_at = now + timedelta(seconds=config.oauth_client_ttl_seconds)
        self._repository.delete_expired_clients(now=now)

        persisted = {
            "client_id": client_id,
            "client_secret_hash": self._hash_secret(client_secret) if client_secret else None,
            "client_name": self._optional_str(payload.get("client_name"), max_len=255),
            "redirect_uris": redirect_uris,
            "grant_types": grant_types,
            "response_types": response_types,
            "scope": scope,
            "token_endpoint_auth_method": auth_method,
            "client_uri": self._optional_url(payload.get("client_uri")),
            "logo_uri": self._optional_url(payload.get("logo_uri")),
            "contacts": contacts,
            "expires_at": expires_at,
        }
        self._repository.create_client(payload=persisted)

        response = {
            "client_id": client_id,
            "client_id_issued_at": issued_at,
            "redirect_uris": redirect_uris,
            "grant_types": grant_types,
            "response_types": response_types,
            "scope": scope,
            "token_endpoint_auth_method": auth_method,
            "client_name": persisted["client_name"],
            "client_uri": persisted["client_uri"],
            "logo_uri": persisted["logo_uri"],
            "contacts": contacts,
        }
        if client_secret:
            response["client_secret"] = client_secret
            response["client_secret_expires_at"] = 0
        return {key: value for key, value in response.items() if value is not None}

    def _validate_redirect_uris(self, value: Any, config: MCPOAuthConfig) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ForgeError("redirect_uris is required", status_code=400)
        allowed_hosts = {host.lower().strip() for host in config.oauth_allowed_redirect_hosts if host.strip()}
        normalized = []
        for raw in value:
            uri = str(raw or "").strip()
            parsed = urlparse(uri)
            host = str(parsed.hostname or "").lower().strip()
            if not host or not parsed.netloc:
                raise ForgeError("redirect_uris must contain valid absolute HTTPS URLs", status_code=400)
            if self._is_allowed_loopback_redirect(parsed.scheme.lower(), host, config):
                normalized.append(uri)
                continue
            if parsed.scheme.lower() != "https":
                raise ForgeError("redirect_uris must contain valid absolute HTTPS URLs", status_code=400)
            if not self._host_allowed(host, allowed_hosts):
                raise ForgeError("redirect_uri host is not allowed", status_code=400, details={"host": host})
            normalized.append(uri)
        return sorted(set(normalized))

    def _validate_response_types(self, value: Any) -> list[str]:
        response_types = self._validate_optional_string_list(value, "response_types") or ["code"]
        if response_types != ["code"]:
            raise ForgeError("response_types must be code", status_code=400)
        return response_types

    def _validate_grant_types(self, value: Any, config: MCPOAuthConfig) -> list[str]:
        grant_types = self._validate_optional_string_list(value, "grant_types") or ["authorization_code"]
        supported = set(BASE_SUPPORTED_GRANT_TYPES)
        if config.oauth_enable_refresh_tokens:
            supported.add("refresh_token")
        unsupported = [grant_type for grant_type in grant_types if grant_type not in supported]
        if unsupported:
            raise ForgeError(
                "grant_types contains unsupported values",
                status_code=400,
                details={"unsupported": unsupported},
            )
        return grant_types

    def _validate_scope(self, value: Any) -> str:
        requested = str(value or " ".join(MCP_OAUTH_SCOPES)).strip()
        scopes = [scope for scope in requested.split(" ") if scope]
        supported = set(MCP_OAUTH_SCOPES)
        unsupported = [scope for scope in scopes if scope not in supported]
        if unsupported:
            raise ForgeError("scope contains unsupported values", status_code=400, details={"unsupported": unsupported})
        return " ".join(dict.fromkeys(scopes))

    def _validate_auth_method(self, value: Any) -> str:
        method = str(value or "none").strip()
        if method not in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS:
            raise ForgeError("Unsupported token_endpoint_auth_method", status_code=400)
        return method

    def _validate_optional_string_list(self, value: Any, field_name: str) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ForgeError(f"{field_name} must be a list", status_code=400)
        normalized = [str(item or "").strip() for item in value if str(item or "").strip()]
        return normalized or None

    def _optional_str(self, value: Any, *, max_len: int) -> str | None:
        token = str(value or "").strip()
        if token == "":
            return None
        return token[:max_len]

    def _optional_url(self, value: Any) -> str | None:
        token = str(value or "").strip()
        if token == "":
            return None
        parsed = urlparse(token)
        if parsed.scheme.lower() not in {"https", "http"} or not parsed.netloc:
            raise ForgeError("client_uri and logo_uri must be absolute URLs", status_code=400)
        return token

    def _host_allowed(self, host: str, allowed_hosts: set[str]) -> bool:
        return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)

    def _is_allowed_loopback_redirect(self, scheme: str, host: str, config: MCPOAuthConfig) -> bool:
        if not config.oauth_allow_loopback_redirects or scheme not in {"http", "https"}:
            return False
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _hash_secret(self, secret: str | None) -> str | None:
        if secret is None:
            return None
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()


__all__ = ["DynamicClientRegistrationService"]

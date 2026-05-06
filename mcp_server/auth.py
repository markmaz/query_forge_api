from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Protocol

from mcp.server.fastmcp import Context
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config.mcp_oauth_config import MCPOAuthConfig, load_mcp_oauth_config
from app.exceptions.forge_error import ForgeError
from app.services.auth_service import AuthService
from app.services.mcp_oauth.access_service import MCPOAuthAccessService
from app.services.query_studio.domain_explorer_service import QueryStudioDomainExplorerService
from app.services.rbac_service import get_effective_roles, workspace_has_feature
from app.services.workspace_access_service import WorkspaceAccessService
from app.utils.jwt_claims import claim_is_admin, get_roles_from_claim

from .config import MCPSettings
from .context import RequestContext
from .exceptions import MCPError


class AuthResolver(Protocol):
    def __call__(self, workspace_id: str, ctx: Context) -> RequestContext: ...


def _extract_user_context(payload: Mapping[str, Any]) -> tuple[str, bool, list[str]]:
    user_id = (
        payload.get("user_id")
        or payload.get("uid")
        or payload.get("sub")
        or payload.get("username")
        or payload.get("email")
    )
    roles = [str(role or "").strip() for role in get_roles_from_claim(dict(payload or {}))]
    is_admin = claim_is_admin(dict(payload or {}))
    return str(user_id or "").strip(), bool(is_admin), roles


def _extract_principal(payload: Mapping[str, Any]) -> tuple[str, str]:
    principal_type = str(payload.get("principal_type") or "user").strip().lower() or "user"
    principal_id = str(payload.get("principal_id") or payload.get("sub") or payload.get("user_id") or "").strip()
    return principal_type, principal_id


def _extract_scopes(payload: Mapping[str, Any]) -> list[str]:
    raw_scope = payload.get("scope") or payload.get("scp") or ""
    if isinstance(raw_scope, str):
        values = raw_scope.split(" ")
    elif isinstance(raw_scope, Iterable):
        values = [str(scope or "") for scope in raw_scope]
    else:
        values = []
    return list(dict.fromkeys(scope.strip() for scope in values if scope.strip()))


def _extract_client_id(payload: Mapping[str, Any], *, fallback: str = "") -> str:
    return str(payload.get("client_id") or payload.get("azp") or fallback or "").strip()


class FastMCPRequestAuthenticator:
    def __init__(
        self,
        *,
        token_verifier: Callable[[str], Mapping[str, Any] | None] | None = None,
        workspace_access_service: WorkspaceAccessService | None = None,
        domain_explorer_service: QueryStudioDomainExplorerService | None = None,
        effective_roles_resolver: Callable[[str, str | None], Iterable[str]] | None = None,
        workspace_feature_checker: Callable[[str, str], bool] | None = None,
        settings: MCPSettings | None = None,
        mcp_access_service: MCPOAuthAccessService | None = None,
        config_loader: Callable[[], MCPOAuthConfig] = load_mcp_oauth_config,
    ) -> None:
        self._verify_token = token_verifier or MCPAccessTokenVerifier(settings=settings).verify
        self._workspace_access = workspace_access_service or WorkspaceAccessService()
        self._domain_explorer = domain_explorer_service or QueryStudioDomainExplorerService()
        self._resolve_roles = effective_roles_resolver or get_effective_roles
        self._workspace_has_feature = workspace_feature_checker or workspace_has_feature
        self._mcp_access = mcp_access_service or MCPOAuthAccessService()
        self._config_loader = config_loader

    def resolve(self, workspace_id: str, ctx: Context) -> RequestContext:
        workspace = str(workspace_id or "").strip()
        if workspace == "":
            raise MCPError(error_code="INVALID_WORKSPACE", message="workspace_id is required", status_code=400)

        request = getattr(getattr(ctx, "request_context", None), "request", None)
        headers = getattr(request, "headers", {}) or {}
        token = self._extract_bearer_token(headers)

        payload = getattr(getattr(request, "state", None), "queryforge_auth_payload", None)
        if payload is None:
            payload = self._verify_token(token)
        if not payload:
            raise MCPError(error_code="UNAUTHORIZED", message="Invalid or expired token", status_code=401)

        try:
            workspace_settings = self._mcp_access.assert_mcp_enabled(workspace_id=workspace)
        except ForgeError as exc:
            raise MCPError(error_code="FORBIDDEN", message=str(exc), status_code=403) from exc
        config = self._config_loader()
        principal_type, principal_id = _extract_principal(payload)
        client_id = _extract_client_id(payload, fallback=principal_id)
        oauth_scopes = _extract_scopes(payload)
        if principal_type == "app":
            return self._resolve_app_context(
                principal_id=principal_id,
                client_id=client_id,
                workspace_id=workspace,
                workspace_settings=workspace_settings,
                oauth_scopes=oauth_scopes,
                ctx=ctx,
            )

        user_id, is_admin, token_roles = _extract_user_context(payload)
        if user_id == "":
            raise MCPError(error_code="UNAUTHORIZED", message="Missing user identity", status_code=401)

        self._workspace_access.assert_workspace_access(user_id=user_id, workspace_id=workspace)
        effective_roles = sorted({str(role or "").strip() for role in self._resolve_roles(user_id, workspace)})
        if is_admin and "super_admin" not in effective_roles:
            effective_roles.append("super_admin")
            effective_roles = sorted(set(effective_roles))

        if config.mcp_require_channel_grant and "queryforge_mcp:user" not in set(effective_roles):
            raise MCPError(
                error_code="FORBIDDEN",
                message="MCP access requires queryforge_mcp:user for this workspace",
                status_code=403,
            )

        allowed_domain_keys = [
            str(row.get("key") or "").strip()
            for row in self._domain_explorer.list_domains(workspace_id=workspace, user_id=user_id)
            if str(row.get("key") or "").strip()
        ]

        query_studio_access = self._has_feature_access(
            feature_key="query_studio",
            workspace_id=workspace,
            effective_roles=effective_roles,
        )
        has_mcp_preview = "queryforge_mcp:preview" in set(effective_roles)
        can_preview = has_mcp_preview and (
            query_studio_access if config.mcp_require_query_studio_for_preview else True
        )
        can_run_saved_queries = can_preview

        return RequestContext(
            user_id=user_id,
            workspace_id=workspace,
            allowed_domain_keys=sorted(set(allowed_domain_keys)),
            can_preview=can_preview,
            can_run_saved_queries=can_run_saved_queries,
            trace_id=str(getattr(ctx, "request_id", "") or "mcp-request"),
            effective_roles=effective_roles,
            is_admin=is_admin or ("workspace_admin" in effective_roles) or ("super_admin" in effective_roles),
            principal_type="user",
            principal_id=user_id,
            client_id=client_id,
            oauth_scopes=oauth_scopes,
            allowed_tools=[],
            preview_row_limit=int(workspace_settings.get("max_preview_row_limit") or 500),
        )

    def _resolve_app_context(
        self,
        *,
        principal_id: str,
        client_id: str,
        workspace_id: str,
        workspace_settings: Mapping[str, Any],
        oauth_scopes: list[str],
        ctx: Context,
    ) -> RequestContext:
        if principal_id == "":
            raise MCPError(error_code="UNAUTHORIZED", message="Missing app principal identity", status_code=401)

        grant = self._mcp_access.get_app_grant(
            principal_type="app",
            principal_id=principal_id,
            workspace_id=workspace_id,
        )
        if not grant:
            raise MCPError(
                error_code="FORBIDDEN",
                message="MCP app principal is not granted access to this workspace",
                status_code=403,
            )

        workspace_limit = int(workspace_settings.get("max_preview_row_limit") or 500)
        grant_limit = int(grant.get("preview_row_limit") or workspace_limit)
        return RequestContext(
            user_id=principal_id,
            workspace_id=workspace_id,
            allowed_domain_keys=sorted(
                {
                    str(domain or "").strip()
                    for domain in list(grant.get("allowed_domain_keys") or [])
                    if str(domain or "").strip()
                }
            ),
            can_preview=bool(grant.get("can_preview")),
            can_run_saved_queries=bool(grant.get("can_preview")),
            trace_id=str(getattr(ctx, "request_id", "") or "mcp-request"),
            effective_roles=[],
            is_admin=False,
            principal_type="app",
            principal_id=principal_id,
            client_id=client_id or principal_id,
            oauth_scopes=oauth_scopes,
            allowed_tools=sorted(
                {
                    str(tool or "").strip()
                    for tool in list(grant.get("allowed_tools") or [])
                    if str(tool or "").strip()
                }
            ),
            preview_row_limit=max(1, min(grant_limit, workspace_limit)),
        )

    @staticmethod
    def _extract_bearer_token(headers: Mapping[str, Any]) -> str:
        header = str(headers.get("authorization") or headers.get("Authorization") or "").strip()
        if header == "":
            raise MCPError(error_code="UNAUTHORIZED", message="Authorization header is required", status_code=401)
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token.strip() == "":
            raise MCPError(error_code="UNAUTHORIZED", message="Bearer token is required", status_code=401)
        return token.strip()

    def _has_feature_access(self, *, feature_key: str, workspace_id: str, effective_roles: list[str]) -> bool:
        role_set = {str(role or "").strip() for role in effective_roles}
        if "super_admin" in role_set or "workspace_admin" in role_set:
            return True
        if not self._workspace_has_feature(workspace_id, feature_key):
            return False
        return f"{feature_key}:user" in role_set or f"{feature_key}:admin" in role_set


class MCPAccessTokenVerifier:
    def __init__(
        self,
        *,
        settings: MCPSettings | None = None,
        decoder: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self._settings = settings or MCPSettings.from_env()
        auth_service = AuthService()
        self._decode = decoder or (lambda token: auth_service.decode_and_verify(token, expected_typ="mcp_access"))

    def verify(self, token: str) -> Mapping[str, Any] | None:
        try:
            payload = self._decode(token)
        except Exception:
            return None
        if not payload:
            return None
        if payload.get("typ") != "mcp_access":
            return None
        if str(payload.get("sub") or payload.get("user_id") or "").strip() == "":
            return None
        if not self._audience_matches(payload.get("aud")):
            return None
        return payload

    def _audience_matches(self, audience: object) -> bool:
        expected = self._settings.resource_url.rstrip("/")
        if isinstance(audience, str):
            return audience.rstrip("/") == expected
        if isinstance(audience, Iterable):
            return any(str(value or "").rstrip("/") == expected for value in audience)
        return False


def _www_authenticate_header(settings: MCPSettings) -> str:
    resource = settings.resource_url.rstrip("/")
    metadata = f"{resource}/.well-known/oauth-protected-resource"
    return (
        'Bearer error="invalid_token", '
        'error_description="A valid QueryForge MCP access token is required", '
        f'resource_metadata="{metadata}"'
    )


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        token_verifier: Callable[[str], Mapping[str, Any] | None] | None = None,
        settings: MCPSettings | None = None,
    ):
        super().__init__(app)
        self._settings = settings or MCPSettings.from_env()
        self._verify_token = token_verifier or MCPAccessTokenVerifier(settings=self._settings).verify

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in {"/.well-known/oauth-protected-resource", "/healthz"}:
            return await call_next(request)
        header = str(request.headers.get("authorization") or "").strip()
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token.strip() == "":
            return JSONResponse(
                {"error_code": "UNAUTHORIZED", "message": "Bearer token is required", "details": {}},
                status_code=401,
                headers={"WWW-Authenticate": _www_authenticate_header(self._settings)},
            )
        payload = self._verify_token(token.strip())
        if not payload:
            return JSONResponse(
                {"error_code": "UNAUTHORIZED", "message": "Invalid or expired token", "details": {}},
                status_code=401,
                headers={"WWW-Authenticate": _www_authenticate_header(self._settings)},
            )
        request.state.queryforge_auth_payload = dict(payload)
        return await call_next(request)

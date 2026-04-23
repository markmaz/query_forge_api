from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Protocol

from mcp.server.fastmcp import Context
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.services.auth_service import AuthService
from app.services.query_studio.domain_explorer_service import QueryStudioDomainExplorerService
from app.services.rbac_service import get_effective_roles, workspace_has_feature
from app.services.workspace_access_service import WorkspaceAccessService
from app.utils.jwt_claims import claim_is_admin, get_roles_from_claim

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


class FastMCPRequestAuthenticator:
    def __init__(
        self,
        *,
        token_verifier: Callable[[str], Mapping[str, Any] | None] | None = None,
        workspace_access_service: WorkspaceAccessService | None = None,
        domain_explorer_service: QueryStudioDomainExplorerService | None = None,
        effective_roles_resolver: Callable[[str, str | None], Iterable[str]] | None = None,
        workspace_feature_checker: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._verify_token = token_verifier or AuthService().verify_token
        self._workspace_access = workspace_access_service or WorkspaceAccessService()
        self._domain_explorer = domain_explorer_service or QueryStudioDomainExplorerService()
        self._resolve_roles = effective_roles_resolver or get_effective_roles
        self._workspace_has_feature = workspace_feature_checker or workspace_has_feature

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

        user_id, is_admin, token_roles = _extract_user_context(payload)
        if user_id == "":
            raise MCPError(error_code="UNAUTHORIZED", message="Missing user identity", status_code=401)

        self._workspace_access.assert_workspace_access(user_id=user_id, workspace_id=workspace)
        effective_roles = sorted({str(role or "").strip() for role in self._resolve_roles(user_id, workspace)})
        if is_admin and "super_admin" not in effective_roles:
            effective_roles.append("super_admin")
            effective_roles = sorted(set(effective_roles))

        allowed_domain_keys = [
            str(row.get("key") or "").strip()
            for row in self._domain_explorer.list_domains(workspace_id=workspace, user_id=user_id)
            if str(row.get("key") or "").strip()
        ]

        can_preview = self._has_feature_access(
            feature_key="query_studio",
            workspace_id=workspace,
            effective_roles=effective_roles,
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


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, token_verifier: Callable[[str], Mapping[str, Any] | None] | None = None):
        super().__init__(app)
        self._verify_token = token_verifier or AuthService().verify_token

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        header = str(request.headers.get("authorization") or "").strip()
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token.strip() == "":
            return JSONResponse(
                {"error_code": "UNAUTHORIZED", "message": "Bearer token is required", "details": {}},
                status_code=401,
            )
        payload = self._verify_token(token.strip())
        if not payload:
            return JSONResponse(
                {"error_code": "UNAUTHORIZED", "message": "Invalid or expired token", "details": {}},
                status_code=401,
            )
        request.state.queryforge_auth_payload = dict(payload)
        return await call_next(request)

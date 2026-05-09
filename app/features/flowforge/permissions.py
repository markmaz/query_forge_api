from __future__ import annotations

from typing import Any, Callable

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.repositories import FlowForgeWorkflowRepository
from app.services.rbac_service import get_effective_roles

WORKFLOW_PERMISSION_LEVELS: dict[str, int] = {
    "view": 10,
    "run": 20,
    "manage_runs": 30,
    "edit": 40,
    "manage": 50,
    "owner": 60,
}

ROLE_PERMISSION_FALLBACKS: dict[str, str] = {
    "flowforge:viewer": "view",
    "flowforge:user": "view",
    "flowforge:operator": "manage_runs",
    "flowforge:designer": "edit",
    "flowforge:admin": "manage",
    "workspace_admin": "manage",
    "super_admin": "owner",
}

WORKFLOW_PERMISSION_NAMES = tuple(WORKFLOW_PERMISSION_LEVELS)


class WorkflowPermissionService:
    def __init__(
        self,
        *,
        workflow_repository: FlowForgeWorkflowRepository | None = None,
        role_loader: Callable[[str, str | None], set[str]] | None = None,
    ) -> None:
        self._workflow_repository = workflow_repository or FlowForgeWorkflowRepository()
        self._role_loader = role_loader or get_effective_roles

    def effective_permission(
        self,
        *,
        workspace_id: str,
        user_id: str,
        workflow_definition: dict[str, Any],
        effective_roles: set[str] | None = None,
    ) -> str | None:
        roles = self._roles(workspace_id=workspace_id, user_id=user_id, effective_roles=effective_roles)
        candidates: list[str] = []

        for role_name, permission in ROLE_PERMISSION_FALLBACKS.items():
            if role_name in roles:
                candidates.append(permission)

        owner_user_id = str(workflow_definition.get("owner_user_id") or workflow_definition.get("created_by") or "").strip()
        if owner_user_id and owner_user_id == str(user_id or "").strip():
            candidates.append("owner")

        workflow_id = self._workflow_definition_id(workflow_definition)
        if workflow_id is not None:
            for acl_row in self._active_acl_rows(workspace_id=workspace_id, workflow_definition_id=workflow_id):
                permission = self._permission_from_acl_row(acl_row=acl_row, user_id=user_id, roles=roles)
                if permission:
                    candidates.append(permission)

        return self._highest_permission(candidates)

    def can(
        self,
        *,
        workspace_id: str,
        user_id: str,
        workflow_definition: dict[str, Any],
        required_permission: str,
        effective_roles: set[str] | None = None,
    ) -> bool:
        effective = self.effective_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            workflow_definition=workflow_definition,
            effective_roles=effective_roles,
        )
        return self._allows(effective_permission=effective, required_permission=required_permission)

    def ensure(
        self,
        *,
        workspace_id: str,
        user_id: str,
        workflow_definition: dict[str, Any],
        required_permission: str,
        effective_roles: set[str] | None = None,
    ) -> str:
        effective = self.effective_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            workflow_definition=workflow_definition,
            effective_roles=effective_roles,
        )
        if not self._allows(effective_permission=effective, required_permission=required_permission):
            raise ForgeError(f"Workflow permission '{required_permission}' is required.", status_code=403)
        return str(effective)

    def can_view_workflow(self, **kwargs: Any) -> bool:
        return self.can(required_permission="view", **kwargs)

    def can_run_workflow(self, **kwargs: Any) -> bool:
        return self.can(required_permission="run", **kwargs)

    def can_manage_runs(self, **kwargs: Any) -> bool:
        return self.can(required_permission="manage_runs", **kwargs)

    def can_edit_workflow(self, **kwargs: Any) -> bool:
        return self.can(required_permission="edit", **kwargs)

    def can_manage_workflow(self, **kwargs: Any) -> bool:
        return self.can(required_permission="manage", **kwargs)

    def can_own_workflow(self, **kwargs: Any) -> bool:
        return self.can(required_permission="owner", **kwargs)

    def _roles(self, *, workspace_id: str, user_id: str, effective_roles: set[str] | None) -> set[str]:
        if effective_roles is not None:
            return set(effective_roles)
        if not user_id:
            return set()
        return set(self._role_loader(str(user_id), str(workspace_id or "").strip() or None))

    def _active_acl_rows(self, *, workspace_id: str, workflow_definition_id: int) -> list[dict[str, Any]]:
        list_acl = getattr(self._workflow_repository, "list_workflow_acl", None)
        if not callable(list_acl):
            return []
        return list_acl(workspace_id=workspace_id, workflow_definition_id=workflow_definition_id)

    @staticmethod
    def _workflow_definition_id(workflow_definition: dict[str, Any]) -> int | None:
        raw_id = workflow_definition.get("id")
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _permission_from_acl_row(*, acl_row: dict[str, Any], user_id: str, roles: set[str]) -> str | None:
        permission = str(acl_row.get("permission") or "").strip()
        if permission not in WORKFLOW_PERMISSION_LEVELS:
            return None

        principal_type = str(acl_row.get("principal_type") or "").strip().lower()
        principal_id = str(acl_row.get("principal_id") or "").strip()

        if principal_type == "user" and principal_id == str(user_id or "").strip():
            return permission
        if principal_type in {"workspace_role", "role"} and principal_id in roles:
            return permission
        if principal_type == "workspace" and principal_id:
            return permission
        return None

    @staticmethod
    def _highest_permission(permissions: list[str]) -> str | None:
        valid_permissions = [permission for permission in permissions if permission in WORKFLOW_PERMISSION_LEVELS]
        if not valid_permissions:
            return None
        return max(valid_permissions, key=lambda permission: WORKFLOW_PERMISSION_LEVELS[permission])

    @staticmethod
    def _allows(*, effective_permission: str | None, required_permission: str) -> bool:
        if required_permission not in WORKFLOW_PERMISSION_LEVELS:
            raise ForgeError(f"Unknown workflow permission '{required_permission}'.", status_code=500)
        if effective_permission not in WORKFLOW_PERMISSION_LEVELS:
            return False
        return WORKFLOW_PERMISSION_LEVELS[effective_permission] >= WORKFLOW_PERMISSION_LEVELS[required_permission]

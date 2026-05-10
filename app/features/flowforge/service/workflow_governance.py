from __future__ import annotations

import logging
from typing import Any

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.models import WorkflowDefinition
from app.features.flowforge.permissions import WORKFLOW_PERMISSION_LEVELS, WORKFLOW_PERMISSION_NAMES

logger = logging.getLogger(__name__)


class FlowForgeWorkflowGovernanceServiceMixin:
    def list_workflow_run_as_principals(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        actor = str(actor_user_id or "").strip()
        items: list[dict[str, Any]] = []
        if actor:
            items.append(
                {
                    "principal_type": "user",
                    "principal_id": actor,
                    "display_name": "Current user",
                    "description": "Allowed for draft and development workflow runs.",
                    "status": "available",
                    "production_eligible": False,
                }
            )
        workspace = str(workspace_id or "").strip()
        if workspace:
            items.append(
                {
                    "principal_type": "workspace_principal",
                    "principal_id": workspace,
                    "display_name": "Workspace principal",
                    "description": "Workspace-level automation identity for production workflows.",
                    "status": "available",
                    "production_eligible": True,
                }
            )
        items.extend(self._service_principal_run_as_options(workspace_id=workspace))
        return {"workspace_id": workspace, "items": items}

    def get_workflow_permissions(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        actor_user_id: str,
        effective_roles: set[str] | None = None,
    ) -> dict[str, Any]:
        definition = self._workflow_definition_or_404(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        self._ensure_workflow_permission(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
            workflow_definition=definition,
            required_permission="manage",
        )
        return {
            "workflow_definition_id": workflow_definition_id,
            "items": self._serialize_workflow_acl(
                self._workflow_repository.list_workflow_acl(
                    workspace_id=workspace_id,
                    workflow_definition_id=workflow_definition_id,
                )
            ),
        }

    def update_workflow_permissions(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
        effective_roles: set[str] | None = None,
    ) -> dict[str, Any]:
        definition = self._workflow_definition_or_404(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        self._ensure_workflow_permission(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
            workflow_definition=definition,
            required_permission="manage",
        )
        grants = payload.get("permissions")
        if not isinstance(grants, list):
            grants = payload.get("grants") if isinstance(payload.get("grants"), list) else []
        revocations = payload.get("revocations") if isinstance(payload.get("revocations"), list) else []
        for entry in grants:
            if not isinstance(entry, dict):
                raise ForgeError("Permission entries must be objects.", status_code=400)
            principal_type, principal_id = self._workflow_acl_principal(entry)
            permission = str(entry.get("permission") or "").strip()
            if permission not in WORKFLOW_PERMISSION_NAMES:
                raise ForgeError("permission is invalid.", status_code=400)
            self._workflow_repository.grant_workflow_permission(
                workspace_id=workspace_id,
                workflow_definition_id=workflow_definition_id,
                principal_type=principal_type,
                principal_id=principal_id,
                permission=permission,
                granted_by=self._optional_string(actor_user_id),
            )
        for entry in revocations:
            if not isinstance(entry, dict):
                raise ForgeError("Revocation entries must be objects.", status_code=400)
            principal_type, principal_id = self._workflow_acl_principal(entry)
            self._workflow_repository.revoke_workflow_permission(
                workspace_id=workspace_id,
                workflow_definition_id=workflow_definition_id,
                principal_type=principal_type,
                principal_id=principal_id,
                revoked_by=self._optional_string(actor_user_id),
            )
        return self.get_workflow_permissions(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
        )

    def update_workflow_owner(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
        effective_roles: set[str] | None = None,
    ) -> WorkflowDefinition:
        definition = self._workflow_definition_or_404(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        self._ensure_workflow_permission(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
            workflow_definition=definition,
            required_permission="manage",
        )
        owner_user_id = str(payload.get("owner_user_id") or "").strip()
        if not owner_user_id:
            raise ForgeError("owner_user_id is required.", status_code=400)
        updated = self._workflow_repository.update_workflow_owner(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            owner_user_id=owner_user_id,
            updated_by=self._optional_string(actor_user_id),
        )
        if not updated:
            raise ForgeError(f"Workflow definition '{workflow_definition_id}' was not found.", status_code=404)
        self._workflow_repository.grant_workflow_permission(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            principal_type="user",
            principal_id=owner_user_id,
            permission="owner",
            granted_by=self._optional_string(actor_user_id),
        )
        refreshed = self._workflow_definition_or_404(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        return self._serialize_workflow_definition(
            refreshed,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
        )

    def update_workflow_run_as(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
        effective_roles: set[str] | None = None,
    ) -> WorkflowDefinition:
        definition = self._workflow_definition_or_404(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        self._ensure_workflow_permission(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
            workflow_definition=definition,
            required_permission="manage",
        )
        principal_type = str(payload.get("principal_type") or "").strip().lower()
        principal_id = str(payload.get("principal_id") or "").strip()
        if principal_type not in {"user", "service_principal", "workspace_principal"}:
            raise ForgeError("principal_type must be user, service_principal, or workspace_principal.", status_code=400)
        if not principal_id:
            raise ForgeError("principal_id is required.", status_code=400)
        if not self._run_as_principal_is_available(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            principal_type=principal_type,
            principal_id=principal_id,
        ):
            raise ForgeError("Run-as principal is not available in this workspace.", status_code=400)
        updated = self._workflow_repository.update_workflow_run_as(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            principal_type=principal_type,
            principal_id=principal_id,
            updated_by=self._optional_string(actor_user_id),
        )
        if not updated:
            raise ForgeError(f"Workflow definition '{workflow_definition_id}' was not found.", status_code=404)
        refreshed = self._workflow_definition_or_404(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        return self._serialize_workflow_definition(
            refreshed,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
        )

    def _workflow_definition_or_404(self, *, workspace_id: str, workflow_definition_id: int) -> dict[str, Any]:
        definition = self._workflow_repository.get_workflow_definition(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        if definition is None:
            raise ForgeError(f"Workflow definition '{workflow_definition_id}' was not found.", status_code=404)
        return definition

    def _workflow_acl_principal(self, entry: dict[str, Any]) -> tuple[str, str]:
        principal_type = str(entry.get("principal_type") or "").strip().lower()
        principal_id = str(entry.get("principal_id") or "").strip()
        if principal_type not in {"user", "workspace_role", "role", "workspace"}:
            raise ForgeError("principal_type is invalid.", status_code=400)
        if not principal_id:
            raise ForgeError("principal_id is required.", status_code=400)
        if principal_type == "role":
            principal_type = "workspace_role"
        return principal_type, principal_id

    def _serialize_workflow_acl(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": row.get("id"),
                "principal_type": row.get("principal_type"),
                "principal_id": row.get("principal_id"),
                "permission": row.get("permission"),
                "granted_by": row.get("granted_by"),
                "granted_at": self._json_scalar(row.get("granted_at")),
            }
            for row in rows
        ]

    def _effective_workflow_permissions(
        self,
        *,
        workspace_id: str,
        workflow_definition: dict[str, Any],
        actor_user_id: str | None,
        effective_roles: set[str] | None,
    ) -> dict[str, Any]:
        actor = str(actor_user_id or "").strip()
        if not actor:
            return {
                "permission": None,
                "can_view": False,
                "can_run": False,
                "can_manage_runs": False,
                "can_edit": False,
                "can_manage": False,
                "can_own": False,
            }
        permission = self._workflow_permission_service.effective_permission(
            workspace_id=workspace_id,
            user_id=actor,
            workflow_definition=workflow_definition,
            effective_roles=effective_roles,
        )
        level = WORKFLOW_PERMISSION_LEVELS.get(str(permission or ""), 0)
        return {
            "permission": permission,
            "can_view": level >= WORKFLOW_PERMISSION_LEVELS["view"],
            "can_run": level >= WORKFLOW_PERMISSION_LEVELS["run"],
            "can_manage_runs": level >= WORKFLOW_PERMISSION_LEVELS["manage_runs"],
            "can_edit": level >= WORKFLOW_PERMISSION_LEVELS["edit"],
            "can_manage": level >= WORKFLOW_PERMISSION_LEVELS["manage"],
            "can_own": level >= WORKFLOW_PERMISSION_LEVELS["owner"],
        }

    def _service_principal_run_as_options(self, *, workspace_id: str) -> list[dict[str, Any]]:
        try:
            from app.services.mcp_oauth.app_principal_service import MCPAppPrincipalService

            principals = MCPAppPrincipalService().list_principals(workspace_id=workspace_id)
        except Exception:  # noqa: BLE001
            logger.exception("flowforge_run_as_service_principal_lookup_failed workspace_id=%s", workspace_id)
            return []
        items = principals.get("items") if isinstance(principals, dict) else []
        result: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            grant = item.get("grant") if isinstance(item.get("grant"), dict) else {}
            if item.get("revoked_at") or grant.get("revoked_at") or not bool(grant.get("enabled")):
                continue
            client_id = str(item.get("client_id") or "").strip()
            if not client_id:
                continue
            result.append(
                {
                    "principal_type": "service_principal",
                    "principal_id": client_id,
                    "display_name": str(item.get("display_name") or client_id),
                    "description": item.get("description"),
                    "status": "available",
                    "production_eligible": True,
                }
            )
        return result

    def _run_as_principal_is_available(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        principal_type: str,
        principal_id: str,
    ) -> bool:
        if principal_type == "user":
            return principal_id == str(actor_user_id or "").strip()
        principals = self.list_workflow_run_as_principals(workspace_id=workspace_id, actor_user_id=actor_user_id)
        return any(
            item.get("principal_type") == principal_type and item.get("principal_id") == principal_id
            for item in principals.get("items", [])
            if isinstance(item, dict)
        )

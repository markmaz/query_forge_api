from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.permissions import WorkflowPermissionService


class _WorkflowRepo:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])
        self.calls = []

    def list_workflow_acl(self, *, workspace_id: str, workflow_definition_id: int):
        self.calls.append((workspace_id, workflow_definition_id))
        return list(self.rows)


def _workflow(**overrides):
    workflow = {
        "id": 12,
        "workspace_id": "ws-1",
        "owner_user_id": "owner-1",
        "created_by": "creator-1",
    }
    workflow.update(overrides)
    return workflow


def test_workflow_permission_service_gives_workspace_admin_manage_access():
    service = WorkflowPermissionService(workflow_repository=_WorkflowRepo())

    permission = service.effective_permission(
        workspace_id="ws-1",
        user_id="admin-1",
        workflow_definition=_workflow(),
        effective_roles={"workspace_admin"},
    )

    assert permission == "manage"
    assert service.can_manage_workflow(
        workspace_id="ws-1",
        user_id="admin-1",
        workflow_definition=_workflow(),
        effective_roles={"workspace_admin"},
    )
    assert not service.can_own_workflow(
        workspace_id="ws-1",
        user_id="admin-1",
        workflow_definition=_workflow(),
        effective_roles={"workspace_admin"},
    )


def test_workflow_permission_service_gives_owner_full_access():
    service = WorkflowPermissionService(workflow_repository=_WorkflowRepo())

    permission = service.effective_permission(
        workspace_id="ws-1",
        user_id="owner-1",
        workflow_definition=_workflow(),
        effective_roles={"flowforge:viewer"},
    )

    assert permission == "owner"
    assert service.can_own_workflow(
        workspace_id="ws-1",
        user_id="owner-1",
        workflow_definition=_workflow(),
        effective_roles={"flowforge:viewer"},
    )


def test_workflow_permission_service_resolves_role_fallbacks():
    service = WorkflowPermissionService(workflow_repository=_WorkflowRepo())

    assert (
        service.effective_permission(
            workspace_id="ws-1",
            user_id="designer-1",
            workflow_definition=_workflow(),
            effective_roles={"flowforge:designer", "flowforge:viewer"},
        )
        == "edit"
    )
    assert (
        service.effective_permission(
            workspace_id="ws-1",
            user_id="operator-1",
            workflow_definition=_workflow(),
            effective_roles={"flowforge:operator", "flowforge:viewer"},
        )
        == "manage_runs"
    )
    assert (
        service.effective_permission(
            workspace_id="ws-1",
            user_id="viewer-1",
            workflow_definition=_workflow(),
            effective_roles={"flowforge:viewer"},
        )
        == "view"
    )


def test_workflow_permission_service_uses_user_acl_rows():
    repo = _WorkflowRepo(
        rows=[
            {
                "principal_type": "user",
                "principal_id": "designer-1",
                "permission": "edit",
            }
        ]
    )
    service = WorkflowPermissionService(workflow_repository=repo)

    assert service.can_edit_workflow(
        workspace_id="ws-1",
        user_id="designer-1",
        workflow_definition=_workflow(),
        effective_roles=set(),
    )
    assert repo.calls == [("ws-1", 12)]


def test_workflow_permission_service_uses_workspace_role_acl_rows():
    service = WorkflowPermissionService(
        workflow_repository=_WorkflowRepo(
            rows=[
                {
                    "principal_type": "workspace_role",
                    "principal_id": "flowforge:operator",
                    "permission": "run",
                }
            ]
        )
    )

    assert service.can_run_workflow(
        workspace_id="ws-1",
        user_id="operator-1",
        workflow_definition=_workflow(),
        effective_roles={"flowforge:operator"},
    )


def test_workflow_permission_service_raises_for_missing_permission():
    service = WorkflowPermissionService(workflow_repository=_WorkflowRepo())

    with pytest.raises(ForgeError) as exc:
        service.ensure(
            workspace_id="ws-1",
            user_id="viewer-1",
            workflow_definition=_workflow(),
            required_permission="edit",
            effective_roles={"flowforge:viewer"},
        )

    assert exc.value.status_code == 403
    assert "edit" in str(exc.value)

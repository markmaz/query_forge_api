import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import exc
from werkzeug.security import generate_password_hash

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.role import Role
from app.models.tenancy.user import User
from app.models.tenancy.user_workspace import UserInvitation
from app.ports.sql_executor import ForgeQueryPort, ForgeQueryTx
from app.services.password_service import validate_password_policy
from app.services.user import (
    UserAdminService,
    UserProfileReadService,
    UserRoleResolutionService,
    UserWorkspaceAccessService,
)
from app.utils.param_guard import validate_params

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._profile_service = UserProfileReadService(sql=self._sql)
        self._workspace_service = UserWorkspaceAccessService(sql=self._sql)
        self._role_service = UserRoleResolutionService(sql=self._sql)
        self._admin_service = UserAdminService(sql=self._sql)

    def update_status(self, user_id: str, status: str):
        return self._admin_service.update_status(self, user_id, status)

    def get_counts(self, *, workspace_id: Optional[str] = None):
        return self._profile_service.get_counts(workspace_id=workspace_id)

    @validate_params("email")
    def resend_invite(self, user_id: str, email: str):
        return self._admin_service.resend_invite(self, user_id, email)

    @validate_params("emails", "workspaces")
    def create_invite_bulk(self, emails: List[str], workspaces: List[dict]):
        return self._admin_service.create_invite_bulk(self, emails, workspaces)

    def create_invite(self, invitation: UserInvitation) -> Dict[str, str]:
        return self._admin_service.create_invite(self, invitation)

    @validate_params("username", "password", "email")
    def create_user(self, username: str, password: str, email: str, first_name: str, last_name: str) -> Dict[str, str]:
        return self._admin_service.create_user(
            self,
            username,
            password,
            email,
            first_name,
            last_name,
            password_validator=validate_password_policy,
        )

    @validate_params("user_id")
    def update_user(
        self,
        user_id: str,
        update_data: "User",
        *,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        current_user = self.get_user(user_id)
        if not current_user:
            raise ForgeError(f"User with ID {user_id} not found", 404)

        update_fields = update_data.model_dump(exclude_unset=True)
        new_workspaces = update_fields.pop("workspaces", None)
        new_rbac_role_names = update_fields.pop("rbac_role_names", None)
        update_fields.pop("rbac_role_ids", None)
        rbac_roles_payload = update_fields.pop("rbac_roles", None)
        if new_rbac_role_names is None and rbac_roles_payload is not None:
            extracted: List[str] = []
            for role_obj in rbac_roles_payload or []:
                if isinstance(role_obj, dict):
                    extracted.append(str(role_obj.get("role_name") or "").strip())
                else:
                    extracted.append(str(getattr(role_obj, "role_name", "")).strip())
            new_rbac_role_names = [name for name in extracted if name]

        params = {"user_id": user_id}
        updates = []

        for field, new_value in update_fields.items():
            if field == "display_name":
                continue
            current_value = getattr(current_user, field, None)

            if field == "password":
                if new_value is None:
                    continue
                if not isinstance(new_value, str) or not new_value.strip():
                    raise ForgeError("Password violates policy rules.", 422)
                validate_password_policy(new_value)
                new_value = generate_password_hash(new_value)
                updates.append(f"{field} = :{field}")
                params[field] = new_value
            elif new_value != current_value:
                updates.append(f"{field} = :{field}")
                params[field] = new_value

        try:
            with self._sql.transaction() as tx:
                if updates:
                    sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id = :user_id"
                    tx.execute_write(sql, params)

                if new_workspaces is not None:
                    self._sync_user_workspaces(tx, user_id, new_workspaces)

                if new_rbac_role_names is not None:
                    self._sync_user_direct_roles(
                        tx,
                        user_id,
                        new_rbac_role_names,
                        workspace_id=workspace_id,
                    )

            if new_rbac_role_names is not None:
                from app.services.rbac_service import invalidate_user_roles

                invalidate_user_roles(user_id, workspace_id=str(workspace_id or "").strip() or None)

            return self.get_user(user_id, workspace_id=workspace_id)

        except exc.SQLAlchemyError as err:
            logger.error("update_user failed for %s: %s", user_id, err)
            raise ForgeError(f"Failed to update user: {str(err)}", 500) from err

    def _sync_user_workspaces(self, tx: ForgeQueryTx, user_id: str, new_ws: List[Dict[str, Any]]) -> None:
        self._workspace_service.sync_user_workspaces(tx, user_id, new_ws)

    def _get_roles_by_names(
        self,
        role_names: List[str],
        *,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Dict[str, Any]]:
        return self._role_service.get_roles_by_names(role_names, tx=tx)

    def _normalize_role_workspace(self, role_name: str, workspace_id: Optional[str]) -> Optional[str]:
        return self._role_service.normalize_role_workspace(role_name, workspace_id)

    def _sync_user_direct_roles(
        self,
        tx: ForgeQueryTx,
        user_id: str,
        new_role_names: List[str],
        *,
        workspace_id: Optional[str] = None,
    ) -> None:
        self._role_service.sync_user_direct_roles(
            self,
            tx,
            user_id,
            new_role_names,
            workspace_id=workspace_id,
        )

    def delete_user(self, user_id: str) -> Dict[str, str]:
        return self._admin_service.delete_user(user_id)

    @validate_params("username")
    def find_user_by_username(self, username: str, workspace_id: Optional[str] = None) -> Optional[User]:
        return self._profile_service.find_user_by_username(self, username, workspace_id=workspace_id)

    @validate_params("username")
    def get_user_by_username(self, username: str, workspace_id: Optional[str] = None) -> User:
        user = self.find_user_by_username(username, workspace_id=workspace_id)
        if not user:
            logger.error("User not found %s", username)
            raise ForgeError("User not found", 404)
        return user

    @validate_params("user_id")
    def get_user(self, user_id: str, workspace_id: Optional[str] = None) -> Optional[User]:
        return self._profile_service.get_user(self, user_id, workspace_id=workspace_id)

    def get_users(
        self,
        status: str = "All",
        cursor: Optional[str] = None,
        limit: int = 10,
        direction: str = "forward",
        username: Optional[str] = None,
        *,
        workspace_id: Optional[str] = None,
    ) -> tuple:
        return self._profile_service.get_users(
            self,
            status=status,
            cursor=cursor,
            limit=limit,
            direction=direction,
            username=username,
            workspace_id=workspace_id,
        )

    @validate_params("user_id", "workspace_id")
    def map_user_workspace(
        self,
        user_id: str,
        workspace_id: str,
        is_default: bool,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        return self._workspace_service.map_user_workspace(self, user_id, workspace_id, is_default, tx=tx)

    @validate_params("user_id")
    def get_user_direct_roles(self, user_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._role_service.get_user_direct_roles(user_id, workspace_id=workspace_id)

    @validate_params("user_id", "role_name")
    def add_user_direct_role(
        self,
        user_id: str,
        role_name: str,
        workspace_id: Optional[str] = None,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        return self._role_service.add_user_direct_role(
            user_id,
            role_name,
            workspace_id=workspace_id,
            tx=tx,
        )

    @validate_params("user_id", "role_name")
    def remove_user_direct_role(
        self,
        user_id: str,
        role_name: str,
        workspace_id: Optional[str] = None,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        return self._role_service.remove_user_direct_role(
            user_id,
            role_name,
            workspace_id=workspace_id,
            tx=tx,
        )

    @validate_params("user_id")
    def replace_user_direct_roles(
        self,
        user_id: str,
        role_names: List[str],
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._role_service.replace_user_direct_roles(
            self,
            user_id,
            role_names,
            workspace_id=workspace_id,
        )

    @validate_params("user_id", "old_role_name", "new_role_name")
    def update_user_direct_role(
        self,
        user_id: str,
        old_role_name: str,
        new_role_name: str,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._role_service.update_user_direct_role(
            self,
            user_id,
            old_role_name,
            new_role_name,
            workspace_id=workspace_id,
        )

    def get_direct_roles_for_users(
        self,
        user_ids: List[str],
        workspace_id: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        return self._role_service.get_direct_roles_for_users(user_ids, workspace_id=workspace_id)

    @validate_params("user_id")
    def get_user_effective_roles(self, user_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._role_service.get_user_effective_roles(user_id, workspace_id=workspace_id)

    def get_role_by_name(self, role_name: str) -> Dict[str, Any]:
        return self._role_service.get_role_by_name(role_name)

    def _assert_user_exists(self, user_id: str) -> None:
        self._role_service.assert_user_exists(user_id)

    def _assert_role_exists(self, role_name: str) -> None:
        self._role_service.assert_role_exists(role_name)

    @validate_params("user_id")
    def get_user_effective_role_names(self, user_id: str, workspace_id: Optional[str] = None) -> List[str]:
        return self._role_service.get_user_effective_role_names(self, user_id, workspace_id=workspace_id)

    @validate_params("user_id", "workspace_id", "is_default")
    def set_workspace_default(self, user_id: str, workspace_id: str, is_default: bool) -> Dict[str, str]:
        return self._workspace_service.set_workspace_default(self, user_id, workspace_id, is_default)

    @validate_params("user_id")
    def get_user_workspaces(self, user_id: str, scope_workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._workspace_service.get_user_workspaces(self, user_id, scope_workspace_id=scope_workspace_id)

    def _user_is_visible_in_workspace(self, user_id: str, workspace_id: str) -> bool:
        return self._workspace_service.user_is_visible_in_workspace(user_id, workspace_id)

    def _get_user_workspaces_bulk(self, user_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        return self._workspace_service.get_user_workspaces_bulk(self, user_ids)

    @validate_params("user_id", "workspace_id")
    def delete_user_workspace(self, user_id: str, workspace_id: str) -> Dict[str, str]:
        return self._workspace_service.delete_user_workspace(user_id, workspace_id)

    @validate_params("username")
    def check_for_existing_user(self, username: str) -> bool:
        return self._profile_service.check_for_existing_user(username)

    def _map_user_row(self, base_row: Dict[str, Any]) -> User:
        return self._profile_service.map_user_row(base_row)

    @staticmethod
    def _to_role_models(rows: List[Dict[str, Any]]) -> List[Role]:
        return UserProfileReadService.to_role_models(rows)

    def update_last_login(self, user_id: str):
        self._profile_service.update_last_login(user_id)

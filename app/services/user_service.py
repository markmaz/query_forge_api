import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import exc
from werkzeug.security import generate_password_hash

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.utils.param_guard import validate_params
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.role import Role
from app.models.tenancy.status_enum import UserStatus
from app.models.tenancy.user import User
from app.models.tenancy.user_workspace import UserInvitation
from app.models.tenancy.user_workspace import UserWorkspace
from app.ports.sql_executor import ForgeQueryPort, ForgeQueryTx
from app.services.password_service import generate_otp_secret, validate_password_policy

logger = logging.getLogger(__name__)

class UserService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def update_status(self, user_id:str, status: str):
        sql = """
            UPDATE users set status = :status WHERE user_id = :user_id
                   """
        
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {"user_id": user_id, "status": status})
            self.update_last_login(user_id)
            return {"message": "Status updated."}
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Database error: {str(e)}", 500)
    def get_counts(self, *, workspace_id: Optional[str] = None):
        normalized_workspace_id = str(workspace_id or "").strip() or None
        sql = """
            SELECT u.status, COUNT(*) as count
            FROM users u
            WHERE u.status IS NOT NULL
        """
        params: Dict[str, Any] = {}
        if normalized_workspace_id:
            sql += """
              AND (
                    EXISTS (
                        SELECT 1
                        FROM workspace_membership wm
                        WHERE wm.user_id = u.user_id
                          AND wm.workspace_id = :workspace_id
                          AND COALESCE(wm.is_active, 1) = 1
                    )
                 OR EXISTS (
                        SELECT 1
                        FROM workspace w
                        JOIN organization_membership om
                          ON om.organization_id = w.organization_id
                         AND om.user_id = u.user_id
                         AND COALESCE(om.is_active, 1) = 1
                        WHERE w.id = :workspace_id
                          AND COALESCE(w.is_active, 1) = 1
                    )
              )
            """
            params["workspace_id"] = normalized_workspace_id
        sql += " GROUP BY u.status"

        try:
            results = self._sql.execute_query_mappings(sql, params)
            counts = {row["status"]: row["count"] for row in results}
            counts["All"] = sum(counts.values())

            for status in UserStatus:
                counts.setdefault(status.value, 0)

            return counts
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Database error: {str(e)}", 500)
    
    validate_params("email")
    def resend_invite(self, user_id:str, email: str):
        from app.tasks.email_tasks import send_invite_email_task
        send_invite_email_task.delay(email, user_id)
        self.update_last_login(user_id)
        return {"email": email, "user_id": user_id}
    
    validate_params("emails", "workspaces")
    def create_invite_bulk(self, emails: List[str], workspaces: List[dict]):
        insert_user_sql = """
            INSERT IGNORE INTO users
            (email, user_id, status, username, password, otp_secret, last_log_in)
            VALUES
            (:email, :user_id, :status, :username, '', :otp, CURRENT_TIMESTAMP)
        """

        invites_sent = 0
        skipped_existing = []

        try:
            with self._sql.transaction() as tx:
                for raw_email in emails:
                    email = (raw_email or "").strip().lower()
                    if not email:
                        continue

                    params = {
                        "email": email,
                        "username": email,
                        "user_id": str(uuid.uuid4()),
                        "status": "Invited",
                        "otp": generate_otp_secret(),
                    }

                    res = tx.execute_write(insert_user_sql, params)

                    # Duplicate? (ignored)
                    if (res or 0) == 0:
                        skipped_existing.append(email)
                        continue

                    user_id = params["user_id"]

                    for workspace in workspaces:
                        self.map_user_workspace(
                            user_id,
                            workspace["workspace_id"],
                            workspace["is_default"],
                            tx,
                        )

                    # send invite email async
                    from app.tasks.email_tasks import send_invite_email_task
                    send_invite_email_task.delay(email, user_id)

                    invites_sent += 1

            return {
                "total_user_count": len(emails),
                "invites_sent": invites_sent,
                "users_skipped": len(skipped_existing),
                "skipped_emails": skipped_existing,
            }

        except exc.SQLAlchemyError as e:
            logger.error(f"create_invite_bulk failed: {e}")
            raise ForgeError(f"Database error: {str(e)}", 500)

    validate_params("email")
    def create_invite(self, invitation: UserInvitation) -> Dict[str, str]:
        if self.check_for_existing_user(invitation.email):
            logger.error(f"User with this username or email already exists: {invitation.email}")
            raise ForgeError("User with this email already exists", 409)

        sql = """
            INSERT INTO users (email, user_id, status, username, password, otp_secret, last_log_in)
            VALUES (:email, :user_id, :status, :email, '', :otp, CURRENT_TIMESTAMP)
        """
        user_id = str(uuid.uuid4())

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {
                    "email": invitation.email,
                    "user_id": user_id,
                    "status": UserStatus.INVITED,
                    "otp": generate_otp_secret()
                })

                for org in invitation.workspaces:
                    self.map_user_workspace(user_id, org.workspace_id, org.is_default, tx)
                
                logger.info(f"User {invitation.email} created successfully")

                from app.tasks.email_tasks import send_invite_email_task
                send_invite_email_task.delay(invitation.email, user_id)

                return {"email": invitation.email, "user_id": user_id}
        except exc.IntegrityError:
            logger.error(f"User with this username or email already exists: {invitation.email}")
            raise ForgeError("User with this username or email already exists", 409)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Database error: {str(e)}", 500)
                    
    validate_params("username", "password", "email")
    def create_user(self, username: str, password: str, email: str, first_name: str, last_name: str) -> Dict[str, str]:
        """
        Creates a new user and inserts it into the database.
        
        :param username: The username of the user.
        :type username: str
        :param password: Password for the user.
        :type passsword: str
        :param email: The email address for the user.
        :type email: str

        Returns:
            dict[str, str]: Success message
        Raises:
            ForgeError 409 (duplicate user), 500 (database error)
        """
        if self.check_for_existing_user(username):
            logger.error(f"User with this username or email already exists: {username}")
            raise ForgeError("User with this username already exists", 409)

        validate_password_policy(password)
        

        hashed_password = generate_password_hash(password)
        user_id = str(uuid.uuid4())

        sql = """
            INSERT INTO users (username, password, email, user_id)
            VALUES (:username, :password, :email, :user_id)
        """
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {
                    "username": username,
                    "password": hashed_password,
                    "email": email,
                    "user_id": user_id,
                    "first_name": first_name,
                    "last_name": last_name
                })
                logger.info(f"User {username}, {email} created successfully")
            return {"username": username, "email": email, "user_id": user_id}
        except exc.IntegrityError:
            logger.error(f"User with this username or email already exists: {username}, {email}")
            raise ForgeError("User with this username or email already exists", 409)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Database error: {str(e)}", 500)

    validate_params("user_id")

    def update_user(
        self,
        user_id: str,
        update_data: "User",
        *,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
            """
            Updates a user and synchronizes related workspaces and direct RBAC roles.
            Expects update_data to optionally include:
            - workspaces: List[{"workspace_id": str|int, "is_default": bool}]
            """
            # 1) Load current user (and fail fast if missing)
            current_user = self.get_user(user_id)
            if not current_user:
                raise ForgeError(f"User with ID {user_id} not found", 404)

            # 2) Prepare scalar field updates on the users table, excluding nested relations
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

            # 3) Apply everything in one transaction
            try:
                with self._sql.transaction() as tx:
                    # 3a) Update users table (only if there are scalar changes)
                    if updates:
                        sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id = :user_id"
                        tx.execute_write(sql, params)

                    # 3b) Sync workspaces junction if provided
                    if new_workspaces is not None:
                        self._sync_user_workspaces(tx, user_id, new_workspaces)

                    # 3c) Sync user-level RBAC roles if provided
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

                # 4) Return fresh copy
                return self.get_user(user_id, workspace_id=workspace_id)

            except exc.SQLAlchemyError as e:
                logger.error(f"update_user failed for {user_id}: {e}")
                raise ForgeError(f"Failed to update user: {str(e)}", 500)


    def _sync_user_workspaces(self, tx: ForgeQueryTx, user_id: str, new_ws: List[Dict[str, Any]]) -> None:
        """
        new_ws: [{"workspace_id": "...", "is_default": bool}, ...]
        """
        # Normalize desired map: workspace_id -> is_default
        desired = {
            str(w["workspace_id"]): bool(w.get("is_default", False))
            for w in (new_ws or [])
        }
        if desired and not any(desired.values()):
            first_key = next(iter(desired.keys()))
            desired[first_key] = True

        # Load existing explicit workspace memberships for this user.
        rows = tx.execute_query_mappings(
            """
            SELECT workspace_id, COALESCE(is_default, 0) AS is_default
            FROM workspace_membership
            WHERE user_id = :uid
            """,
            {"uid": user_id},
        )
        existing = {str(r["workspace_id"]): bool(r["is_default"]) for r in rows}

        to_delete = set(existing) - set(desired)
        to_insert = set(desired) - set(existing)
        to_update = {wid for wid in existing.keys() & desired.keys() if existing[wid] != desired[wid]}

        # Delete removed
        if to_delete:
            ids_list = list(to_delete)
            placeholders = ",".join([f":id{i}" for i in range(len(ids_list))])
            params = {"uid": user_id, **{f"id{i}": wid for i, wid in enumerate(ids_list)}}
            tx.execute_write(
                f"DELETE FROM workspace_membership WHERE user_id = :uid AND workspace_id IN ({placeholders})",
                params,
            )

        # Insert new
        if to_insert:
            for wid in to_insert:
                tx.execute_write(
                    """
                    INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
                    VALUES (:workspace_id, :uid, 'member', 1, :is_default)
                    ON DUPLICATE KEY UPDATE
                      is_active = 1,
                      is_default = VALUES(is_default),
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    {"uid": user_id, "workspace_id": wid, "is_default": 1 if desired[wid] else 0},
                )

        # Update flags where changed
        for wid in to_update:
            tx.execute_write(
                "UPDATE workspace_membership "
                "SET is_default = :is_default "
                "WHERE user_id = :uid AND workspace_id = :workspace_id",
                {"uid": user_id, "workspace_id": wid, "is_default": 1 if desired[wid] else 0},
            )
        if any(desired.values()):
            # keep only the first True as default
            true_ids = [wid for wid, is_def in desired.items() if is_def]
            keep = true_ids[0]
            if len(true_ids) > 1:
                tx.execute_write(
                    "UPDATE workspace_membership SET is_default = 0 "
                    "WHERE user_id = :uid AND workspace_id != :keep",
                    {"uid": user_id, "keep": keep},
                )

    def _get_roles_by_names(
        self,
        role_names: List[str],
        *,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Dict[str, Any]]:
        names = [str(name or "").strip() for name in role_names if str(name or "").strip()]
        if not names:
            return {}
        placeholders = ",".join([f":name{i}" for i in range(len(names))])
        params = {f"name{i}": name for i, name in enumerate(names)}
        query = f"""
            SELECT
                id,
                CAST(id AS CHAR) AS role_id,
                name AS role_name,
                display_name,
                description,
                feature_key,
                is_system
            FROM roles
            WHERE name IN ({placeholders})
        """
        executor = tx.execute_query_mappings if tx is not None else self._sql.execute_query_mappings
        rows = executor(query, params)
        return {
            str(row.get("role_name") or "").strip(): dict(row)
            for row in rows
            if str(row.get("role_name") or "").strip()
        }

    def _normalize_role_workspace(self, role_name: str, workspace_id: Optional[str]) -> Optional[str]:
        role_name = str(role_name or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip() or None
        if role_name == "super_admin":
            return None
        if not normalized_workspace_id:
            raise ForgeError("workspace_id is required for non-global roles", 400)
        return normalized_workspace_id

    def _sync_user_direct_roles(
        self,
        tx: ForgeQueryTx,
        user_id: str,
        new_role_names: List[str],
        *,
        workspace_id: Optional[str] = None,
    ) -> None:
        desired_role_names: Set[str] = {
            str(role_name or "").strip()
            for role_name in (new_role_names or [])
            if str(role_name or "").strip()
        }
        normalized_workspace_id = str(workspace_id or "").strip() or None
        if any(role_name != "super_admin" for role_name in desired_role_names) and not normalized_workspace_id:
            raise ForgeError("workspace_id is required for non-global roles", 400)

        rows = tx.execute_query_mappings(
            """
            SELECT r.id, r.name AS role_name
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :uid
              AND (
                    (ur.workspace_id <=> :workspace_id)
                 OR (ur.workspace_id IS NULL AND r.name = 'super_admin')
              )
            """,
            {"uid": user_id, "workspace_id": normalized_workspace_id},
        )
        existing_role_names = {
            str(row.get("role_name") or "").strip()
            for row in rows
            if str(row.get("role_name") or "").strip()
        }

        to_delete = sorted(existing_role_names - desired_role_names)
        to_insert = sorted(desired_role_names - existing_role_names)

        for role_name in to_delete:
            self.remove_user_direct_role(
                user_id,
                role_name,
                workspace_id=normalized_workspace_id,
                tx=tx,
            )

        for role_name in to_insert:
            self.add_user_direct_role(
                user_id,
                role_name,
                workspace_id=normalized_workspace_id,
                tx=tx,
            )


    @validate_params("user_id")
    def delete_user(self, user_id: str) -> Dict[str, str]:
        """
        Deletes a user from the database.
        
        :parm user_id: The user_id for the user.
        :type user_id: str

        Returns:
            dict[str, str]: Success message
        Raises:
            ForgeError 404 (User not found), 500 (database error)
        """
        delete_user = "DELETE FROM users WHERE user_id = :user_id"
        delete_user_workspace = "DELETE FROM workspace_membership WHERE user_id = :user_id"
        delete_user_org_membership = "DELETE FROM organization_membership WHERE user_id = :user_id"
        delete_user_roles = "DELETE FROM user_roles WHERE user_id = :user_id"
        delete_user_domain_mapping = "DELETE FROM user_domain_mapping WHERE user_id = :user_id"

        try:
            with self._sql.transaction() as tx:
                # Delete dependent rows first to avoid FK violations.
                tx.execute_write(delete_user_roles, {"user_id": user_id})
                tx.execute_write(delete_user_domain_mapping, {"user_id": user_id})
                tx.execute_write(delete_user_workspace, {"user_id": user_id})
                tx.execute_write(delete_user_org_membership, {"user_id": user_id})
                result = tx.execute_write(delete_user, {"user_id": user_id})
                if (result or 0) == 0:
                    logger.error(f"User not found: {user_id}")
                    raise ForgeError("User not found", 404)
            return {"message": "User deleted successfully"}
        except exc.SQLAlchemyError as e:
            logger.error(f"{str(e)}")
            raise ForgeError(f"Failed to delete user: {str(e)}", 500)

    @validate_params("username")
    def find_user_by_username(self, username: str, workspace_id: Optional[str] = None) -> Optional[User]:
        """
        Fetches a user by username and returns None when missing.

        :param username: The username for the user.
        :type username: str

        Returns:
            User | None
        Raises:
            ForgeError 500 (database error)
        """
        sql = """
            SELECT
                user_id,
                username,
                password,
                email,
                first_name,
                last_name,
                tos_accepted,
                eula_accepted,
                status AS user_status,
                otp_secret,
                last_log_in,
                two_factor_preference
            FROM users
            WHERE username = :username
            LIMIT 1
        """
        try:
            result = self._sql.execute_query_mappings(sql, {"username": username})
            if not result:
                return None
            user = self._map_user_row(result[0])
            user.workspaces = [UserWorkspace(**row) for row in self.get_user_workspaces(str(user.user_id))]
            direct_roles = self._to_role_models(
                self.get_user_direct_roles(str(user.user_id), workspace_id=workspace_id)
            )
            user.rbac_roles = direct_roles
            user.rbac_role_ids = [role.role_id for role in direct_roles]
            user.rbac_role_names = [role.role_name for role in direct_roles]
            return user
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Failed to retrieve user: {str(e)}", 500)

    @validate_params("username")
    def get_user_by_username(self, username: str, workspace_id: Optional[str] = None) -> User:
        """
        Fetches a user by username.
        
        :parm username: The username for the user.
        :type username: str

        Returns:
            dict[str, any]: User
        Raises:
            ForgeError 404 (User not found), 500 (database error)
        """
        user = self.find_user_by_username(username, workspace_id=workspace_id)
        if not user:
            logger.error(f"User not found {username}")
            raise ForgeError("User not found", 404)
        return user

    @validate_params("user_id")
    def get_user(self, user_id: str, workspace_id: Optional[str] = None) -> Optional[User]:
        """
        Fetches a user by user_id.
        
        :parm user_id: The user_id for the user.
        :type user_id: str

        Returns:
            dict[str, any]: User
        Raises:
            ForgeError 404 (User not found), 500 (database error)
        """
        sql = """
            SELECT
                user_id,
                username,
                password,
                email,
                first_name,
                last_name,
                tos_accepted,
                eula_accepted,
                status AS user_status,
                otp_secret,
                last_log_in,
                two_factor_preference
            FROM users
            WHERE user_id = :user_id
            LIMIT 1
        """
        try:
            result = self._sql.execute_query_mappings(sql, {"user_id": user_id})
            if not result:
                logger.error(f"User not found {user_id}")
                raise ForgeError("User not found", 404)
            if workspace_id and not self._user_is_visible_in_workspace(str(user_id), workspace_id):
                logger.error(f"User not found in workspace scope {user_id} {workspace_id}")
                raise ForgeError("User not found", 404)
            user = self._map_user_row(result[0])
            user.workspaces = [
                UserWorkspace(**row)
                for row in self.get_user_workspaces(str(user.user_id), scope_workspace_id=workspace_id)
            ]
            direct_roles = self._to_role_models(
                self.get_user_direct_roles(str(user.user_id), workspace_id=workspace_id)
            )
            user.rbac_roles = direct_roles
            user.rbac_role_ids = [role.role_id for role in direct_roles]
            user.rbac_role_names = [role.role_name for role in direct_roles]
            return user
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Failed to retrieve user: {str(e)}", 500)
    

    def get_users(
        self,
        status: str = 'All',
        cursor: Optional[str] = None,
        limit: int = 10,
        direction: str = 'forward',
        username: Optional[str] = None,
        *,
        workspace_id: Optional[str] = None,
    ) -> tuple:
        normalized_workspace_id = str(workspace_id or "").strip() or None
        where_clauses = ["(:status = 'All' OR u.status = :status)", "u.status IS NOT NULL"]
        params = {"status": status, "limit": limit + 1}  # One extra for pagination check

        if username:
            q = str(username or "").strip().lower()
            where_clauses.append(
                """
                (
                    LOWER(COALESCE(u.username, '')) LIKE :username
                    OR LOWER(COALESCE(u.email, '')) LIKE :username
                    OR LOWER(COALESCE(u.first_name, '')) LIKE :username
                    OR LOWER(COALESCE(u.last_name, '')) LIKE :username
                    OR LOWER(CONCAT_WS(' ', COALESCE(u.first_name, ''), COALESCE(u.last_name, ''))) LIKE :username
                )
                """
            )
            params["username"] = f"%{q}%"

        if normalized_workspace_id:
            where_clauses.append(
                """
                (
                    EXISTS (
                        SELECT 1
                        FROM workspace_membership wm
                        WHERE wm.user_id = u.user_id
                          AND wm.workspace_id = :workspace_id
                          AND COALESCE(wm.is_active, 1) = 1
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM workspace w
                        JOIN organization_membership om
                          ON om.organization_id = w.organization_id
                         AND om.user_id = u.user_id
                         AND COALESCE(om.is_active, 1) = 1
                        WHERE w.id = :workspace_id
                          AND COALESCE(w.is_active, 1) = 1
                    )
                )
                """
            )
            params["workspace_id"] = normalized_workspace_id

        where_clause = " AND ".join(where_clauses)

        if cursor:
            if direction == 'forward':
                where_clause += " AND u.user_id > :cursor"
                params["cursor"] = cursor
                order_by = "ORDER BY u.user_id ASC"
            else:
                where_clause += " AND u.user_id < :cursor"
                params["cursor"] = cursor
                order_by = "ORDER BY u.user_id ASC"  # Reverse later
        else:
            order_by = "ORDER BY u.user_id ASC"

        base_user_query = f"""
            SELECT u.user_id, u.username, u.first_name, u.last_name, u.email, u.status, u.tos_accepted,
                u.eula_accepted, u.two_factor_preference, u.last_log_in
            FROM users u
            WHERE {where_clause}
            {order_by}
            LIMIT :limit
        """

        base_rows = self._sql.execute_query_mappings(base_user_query, params)

        if not base_rows:
            return [], None, None, 0

        # Trim extra row for pagination
        trimmed = base_rows[:limit]
        user_ids = [row["user_id"] for row in trimmed]

        workspace_map = self._get_user_workspaces_bulk(user_ids)

        # Build full user models
        users = []
        for base_row in trimmed:
            uid = base_row["user_id"]
            row_dict = dict(base_row)
            row_dict['tos_accepted'] = bool(row_dict.get('tos_accepted'))
            row_dict['eula_accepted'] = bool(row_dict.get('eula_accepted'))

            # Workspaces
            workspaces = [
                UserWorkspace(workspace_id=row.get("workspace_id"), is_default=bool(row.get("is_default")))
                for row in workspace_map.get(str(uid), [])
            ]

            users.append(User(**row_dict, workspaces=workspaces))

        direct_roles_map = self.get_direct_roles_for_users(user_ids, workspace_id=workspace_id)
        for user in users:
            role_rows = direct_roles_map.get(str(user.user_id), [])
            role_models = self._to_role_models(role_rows)
            user.rbac_roles = role_models
            user.rbac_role_ids = [role.role_id for role in role_models]
            user.rbac_role_names = [role.role_name for role in role_models]

        # Pagination cursors
        next_cursor = None
        prev_cursor = None

        if len(base_rows) > limit:
            next_cursor = base_rows[limit - 1]["user_id"]
        if direction == 'forward' and cursor:
            prev_query = f"""
                SELECT u.user_id
                FROM users u
                WHERE {where_clause.replace('u.user_id > :cursor', 'u.user_id < :cursor')}
                ORDER BY u.user_id DESC
                LIMIT 1
            """
            prev_rows = self._sql.execute_query_mappings(prev_query, {**params, "limit": None})
            prev_result = prev_rows[0] if prev_rows else None
            if prev_result:
                prev_cursor = prev_result['user_id']
        elif direction == 'backward' and len(users) > 0:
            next_cursor = users[0].user_id
            users = users[::-1]
            prev_query = f"""
                SELECT u.user_id
                FROM users u
                WHERE {where_clause.replace('u.user_id < :cursor', 'u.user_id < :cursor')}
                ORDER BY u.user_id DESC
                LIMIT 1
            """
            prev_rows = self._sql.execute_query_mappings(
                prev_query,
                {**params, "cursor": users[0].user_id, "limit": None},
            )
            prev_result = prev_rows[0] if prev_rows else None
            if prev_result:
                prev_cursor = prev_result['user_id']

        count_query = f"SELECT COUNT(*) as count FROM users u WHERE {' AND '.join(where_clauses)}"
        count_params = {k: v for k, v in params.items() if k not in {'limit', 'cursor'}}
        count_rows = self._sql.execute_query_mappings(count_query, count_params)
        total_count = count_rows[0].get("count") if count_rows else 0

        return users, next_cursor, prev_cursor, total_count


    @validate_params("user_id", "workspace_id")
    def map_user_workspace(
        self,
        user_id: str,
        workspace_id: str,
        is_default: bool,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        """
        Maps a user to a workspace (organization).

        If is_default is True, it updates other mappings to remove their default status.
        If this is the first mapping, it is automatically made default.

        Parameters:
            user_id (str): The user ID.
            workspace_id (str): The workspace ID.
            is_default (bool): Whether this workspace should be default.
            conn (SQLAlchemy connection, optional): Use existing connection if passed.

        Returns:
            dict: Mapping info

        Raises:
            ForgeError: On duplicate or SQL failure.
        """
        mapping = self.get_user_workspaces(user_id)

        if any(str(w.get('workspace_id')) == str(workspace_id) for w in mapping):
            logger.error(f"User: {user_id} already mapped to workspace {workspace_id}")
            raise ForgeError("Mapping already exists for user", 409)

        try:
            if tx is None:
                with self._sql.transaction() as local_tx:
                    return self.map_user_workspace(user_id, workspace_id, is_default, local_tx)

            # Automatically set default on first mapping
            if not mapping:
                is_default = True
            elif is_default:
                # Remove existing default
                update_sql = """
                    UPDATE workspace_membership
                    SET is_default = false
                    WHERE user_id = :user_id AND is_default = true
                """
                tx.execute_write(update_sql, {"user_id": user_id})

            insert_sql = """
                INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
                VALUES (:workspace_id, :user_id, 'member', 1, :is_default)
                ON DUPLICATE KEY UPDATE
                  is_active = 1,
                  is_default = VALUES(is_default),
                  updated_at = CURRENT_TIMESTAMP
            """
            tx.execute_write(
                insert_sql,
                {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "is_default": 1 if is_default else 0,
                },
            )

            return {
                "message": "User and workspace mapped successfully",
                "mapping": {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "is_default": is_default,
                },
            }
        except exc.SQLAlchemyError as e:
            logger.error(f"SQL error during user mapping: {str(e)}")
            raise ForgeError(f"Failed to map user to workspace: {str(e)}", 500)
    
    @validate_params("user_id")
    def get_user_direct_roles(self, user_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        normalized_workspace_id = str(workspace_id or "").strip() or None
        sql = """
            SELECT
                CAST(r.id AS CHAR) AS role_id,
                r.name AS role_name,
                r.display_name,
                r.description,
                r.feature_key,
                r.is_system
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :user_id
              AND (
                    (ur.workspace_id <=> :workspace_id)
                 OR (ur.workspace_id IS NULL AND r.name = 'super_admin')
              )
            ORDER BY r.name
        """
        try:
            return [
                dict(row)
                for row in self._sql.execute_query_mappings(
                    sql,
                    {"user_id": user_id, "workspace_id": normalized_workspace_id},
                )
            ]
        except exc.SQLAlchemyError as e:
            logger.error(f"Error fetching direct roles for user_id={user_id}: {str(e)}")
            raise ForgeError(f"Failed to retrieve user direct roles: {str(e)}", 500)

    @validate_params("user_id", "role_name")
    def add_user_direct_role(
        self,
        user_id: str,
        role_name: str,
        workspace_id: Optional[str] = None,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        role_name = str(role_name or "").strip()
        self._assert_user_exists(uid)
        role = self.get_role_by_name(role_name)
        role_id = int(role.get("id") or role.get("role_id"))
        normalized_workspace_id = self._normalize_role_workspace(role_name, workspace_id)

        try:
            if tx is None:
                result: Dict[str, Any]
                with self._sql.transaction() as local_tx:
                    exists_rows = local_tx.execute_query_mappings(
                        """
                        SELECT id
                        FROM user_roles
                        WHERE user_id = :user_id
                          AND role_id = :role_id
                          AND workspace_id <=> :workspace_id
                        LIMIT 1
                        """,
                        {
                            "user_id": uid,
                            "role_id": role_id,
                            "workspace_id": normalized_workspace_id,
                        },
                    )
                    if exists_rows:
                        result = {
                            "user_id": uid,
                            "workspace_id": normalized_workspace_id,
                            "role_name": role_name,
                            "created": False,
                        }
                    else:
                        local_tx.execute_write(
                            """
                            INSERT INTO user_roles (user_id, workspace_id, role_id)
                            VALUES (:user_id, :workspace_id, :role_id)
                            """,
                            {
                                "user_id": uid,
                                "workspace_id": normalized_workspace_id,
                                "role_id": role_id,
                            },
                        )
                        result = {
                            "user_id": uid,
                            "workspace_id": normalized_workspace_id,
                            "role_name": role_name,
                            "created": True,
                        }

                from app.services.rbac_service import invalidate_user_roles
                invalidate_user_roles(uid, workspace_id=normalized_workspace_id)
                return result

            exists_rows = tx.execute_query_mappings(
                """
                SELECT id
                FROM user_roles
                WHERE user_id = :user_id
                  AND role_id = :role_id
                  AND workspace_id <=> :workspace_id
                LIMIT 1
                """,
                {
                    "user_id": uid,
                    "role_id": role_id,
                    "workspace_id": normalized_workspace_id,
                },
            )
            if exists_rows:
                return {
                    "user_id": uid,
                    "workspace_id": normalized_workspace_id,
                    "role_name": role_name,
                    "created": False,
                }

            tx.execute_write(
                """
                INSERT INTO user_roles (user_id, workspace_id, role_id)
                VALUES (:user_id, :workspace_id, :role_id)
                """,
                {
                    "user_id": uid,
                    "workspace_id": normalized_workspace_id,
                    "role_id": role_id,
                },
            )
            return {
                "user_id": uid,
                "workspace_id": normalized_workspace_id,
                "role_name": role_name,
                "created": True,
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as e:
            logger.error(f"Error adding direct role for user_id={uid}: {str(e)}")
            raise ForgeError(f"Failed to add user direct role: {str(e)}", 500)

    @validate_params("user_id", "role_name")
    def remove_user_direct_role(
        self,
        user_id: str,
        role_name: str,
        workspace_id: Optional[str] = None,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        role_name = str(role_name or "").strip()
        self._assert_user_exists(uid)
        role = self.get_role_by_name(role_name)
        role_id = int(role.get("id") or role.get("role_id"))
        normalized_workspace_id = self._normalize_role_workspace(role_name, workspace_id)

        try:
            if tx is None:
                result: Dict[str, Any]
                with self._sql.transaction() as local_tx:
                    deleted = local_tx.execute_write(
                        """
                        DELETE FROM user_roles
                        WHERE user_id = :user_id
                          AND role_id = :role_id
                          AND workspace_id <=> :workspace_id
                        """,
                        {
                            "user_id": uid,
                            "role_id": role_id,
                            "workspace_id": normalized_workspace_id,
                        },
                    )
                    if int(deleted or 0) == 0:
                        raise ForgeError("User direct role mapping not found", 404)
                    result = {
                        "user_id": uid,
                        "workspace_id": normalized_workspace_id,
                        "role_name": role_name,
                        "deleted": True,
                    }
                from app.services.rbac_service import invalidate_user_roles
                invalidate_user_roles(uid, workspace_id=normalized_workspace_id)
                return result

            deleted = tx.execute_write(
                """
                DELETE FROM user_roles
                WHERE user_id = :user_id
                  AND role_id = :role_id
                  AND workspace_id <=> :workspace_id
                """,
                {
                    "user_id": uid,
                    "role_id": role_id,
                    "workspace_id": normalized_workspace_id,
                },
            )
            if int(deleted or 0) == 0:
                raise ForgeError("User direct role mapping not found", 404)

            return {
                "user_id": uid,
                "workspace_id": normalized_workspace_id,
                "role_name": role_name,
                "deleted": True,
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as e:
            logger.error(f"Error removing direct role for user_id={uid}: {str(e)}")
            raise ForgeError(f"Failed to remove user direct role: {str(e)}", 500)

    @validate_params("user_id")
    def replace_user_direct_roles(
        self,
        user_id: str,
        role_names: List[str],
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        self._assert_user_exists(uid)

        normalized_role_names: List[str] = []
        seen = set()
        for role_name in role_names or []:
            name = str(role_name or "").strip()
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            normalized_role_names.append(name)

        for name in normalized_role_names:
            self._assert_role_exists(name)

        try:
            with self._sql.transaction() as tx:
                self._sync_user_direct_roles(
                    tx,
                    uid,
                    normalized_role_names,
                    workspace_id=workspace_id,
                )
            from app.services.rbac_service import invalidate_user_roles
            invalidate_user_roles(uid, workspace_id=str(workspace_id or "").strip() or None)
            roles = self.get_user_direct_roles(uid, workspace_id=workspace_id)
            return {
                "user_id": uid,
                "workspace_id": str(workspace_id or "").strip() or None,
                "roles": roles,
                "count": len(roles),
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as e:
            logger.error(f"Error replacing direct roles for user_id={uid}: {str(e)}")
            raise ForgeError(f"Failed to replace user direct roles: {str(e)}", 500)

    @validate_params("user_id", "old_role_name", "new_role_name")
    def update_user_direct_role(
        self,
        user_id: str,
        old_role_name: str,
        new_role_name: str,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        old_role_name = str(old_role_name or "").strip()
        new_role_name = str(new_role_name or "").strip()
        self._assert_user_exists(uid)
        self._assert_role_exists(new_role_name)

        try:
            with self._sql.transaction() as tx:
                self.remove_user_direct_role(uid, old_role_name, workspace_id=workspace_id, tx=tx)
                created = self.add_user_direct_role(uid, new_role_name, workspace_id=workspace_id, tx=tx)
            from app.services.rbac_service import invalidate_user_roles
            invalidate_user_roles(
                uid,
                workspace_id=self._normalize_role_workspace(new_role_name, workspace_id),
            )
            return {
                "user_id": uid,
                "workspace_id": str(workspace_id or "").strip() or None,
                "old_role_name": old_role_name,
                "new_role_name": new_role_name,
                "created": bool(created.get("created")),
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as e:
            logger.error(f"Error updating direct role for user_id={uid}: {str(e)}")
            raise ForgeError(f"Failed to update user direct role: {str(e)}", 500)

    def get_direct_roles_for_users(
        self,
        user_ids: List[str],
        workspace_id: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        ids = [str(uid or "").strip() for uid in user_ids if str(uid or "").strip()]
        if not ids:
            return {}
        normalized_workspace_id = str(workspace_id or "").strip() or None
        placeholders = ",".join([f":uid{i}" for i in range(len(ids))])
        params = {f"uid{i}": uid for i, uid in enumerate(ids)}
        params["workspace_id"] = normalized_workspace_id
        sql = f"""
            SELECT
                ur.user_id,
                CAST(r.id AS CHAR) AS role_id,
                r.name AS role_name,
                r.display_name,
                r.description,
                r.feature_key,
                r.is_system
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id IN ({placeholders})
              AND (
                    (ur.workspace_id <=> :workspace_id)
                 OR (ur.workspace_id IS NULL AND r.name = 'super_admin')
              )
            ORDER BY ur.user_id, r.name
        """
        try:
            rows = self._sql.execute_query_mappings(sql, params)
        except exc.SQLAlchemyError as e:
            logger.error(f"Error fetching direct roles for users: {str(e)}")
            raise ForgeError(f"Failed to retrieve user direct roles: {str(e)}", 500)

        out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            uid = str(row.get("user_id") or "").strip()
            if uid:
                out[uid].append(dict(row))
        return out

    @validate_params("user_id")
    def get_user_effective_roles(self, user_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        from app.services.rbac_service import get_effective_roles

        role_names = sorted(get_effective_roles(str(user_id or "").strip(), workspace_id=workspace_id))
        if not role_names:
            return []

        roles_by_name = self._get_roles_by_names(role_names)
        return [roles_by_name[name] for name in role_names if name in roles_by_name]

    def get_role_by_name(self, role_name: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
                id,
                CAST(id AS CHAR) AS role_id,
                name AS role_name,
                display_name,
                description,
                feature_key,
                is_system
            FROM roles
            WHERE name = :role_name
            LIMIT 1
            """,
            {"role_name": str(role_name)},
        )
        if not rows:
            raise ForgeError("Role not found", 404)
        return dict(rows[0])

    def _assert_user_exists(self, user_id: str) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT user_id
            FROM users
            WHERE user_id = :user_id
            LIMIT 1
            """,
            {"user_id": str(user_id)},
        )
        if not rows:
            raise ForgeError("User not found", 404)

    def _assert_role_exists(self, role_name: str) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM roles
            WHERE name = :role_name
            LIMIT 1
            """,
            {"role_name": str(role_name)},
        )
        if not rows:
            raise ForgeError("Role not found", 404)

    @validate_params("user_id")
    def get_user_effective_role_names(self, user_id: str, workspace_id: Optional[str] = None) -> List[str]:
        roles = self.get_user_effective_roles(user_id, workspace_id=workspace_id)
        names: List[str] = []
        seen = set()
        for row in roles:
            role_name = str(row.get("role_name") or "").strip()
            if not role_name:
                continue
            key = role_name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(role_name)
        return names

    @validate_params("user_id", "workspace_id", "is_default")
    def set_workspace_default(self, user_id: str, workspace_id: str, is_default: bool) -> Dict[str, str]:
        """
        Updates the default workspace mapping for a user.

        Ensures:
        - Exactly one default workspace per user.
        - A user must always have one default workspace.

        :param user_id: The user ID
        :param workspace_id: The workspace to update
        :param is_default: Whether this workspace should be the default
        :return: A success message and updated mapping
        """
        mapping = self.get_user_workspaces(user_id)

        # Find the specific workspace mapping
        current_mapping = next((w for w in mapping if w['workspace_id'] == workspace_id), None)

        if not current_mapping:
            raise ForgeError("Workspace mapping not found for user", 404)

        if current_mapping['is_default'] and not is_default:
            raise ForgeError("User must always have a default workspace", 409)

        try:
            with self._sql.transaction() as tx:
                if is_default:
                    # Unset previous default
                    unset_sql = """
                        UPDATE workspace_membership
                        SET is_default = false
                        WHERE user_id = :user_id
                    """
                    tx.execute_write(unset_sql, {"user_id": user_id})
                    tx.execute_write(
                        """
                        INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
                        VALUES (:workspace_id, :user_id, 'member', 1, 1)
                        ON DUPLICATE KEY UPDATE
                          is_active = 1,
                          is_default = 1,
                          updated_at = CURRENT_TIMESTAMP
                        """,
                        {"user_id": user_id, "workspace_id": workspace_id},
                    )
                else:
                    tx.execute_write(
                        """
                        UPDATE workspace_membership
                        SET is_default = 0
                        WHERE user_id = :user_id AND workspace_id = :workspace_id
                        """,
                        {"user_id": user_id, "workspace_id": workspace_id},
                    )

            return {
                "message": "Workspace default updated successfully",
                "mapping": {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "is_default": is_default
                }
            }

        except exc.SQLAlchemyError as e:
            logger.error(f"SQL error during workspace update: {str(e)}")
            raise ForgeError(f"Failed to update workspace mapping: {str(e)}", 500)

    @validate_params("user_id")
    def get_user_workspaces(self, user_id: str, scope_workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all workspaces for a given user in a single query.
        
        :param user_id: The user ID
        :type user_id: str

        Returns:
            Dict[str, any]: Success Message
        Raises:
            ForgeError 500 (database error)

        """
        effective_role_names = {
            str(role_name or "").strip().lower()
            for role_name in self.get_user_effective_role_names(user_id)
        }
        include_all_workspaces = "super_admin" in effective_role_names
        scope_workspace_value = str(scope_workspace_id or "").strip() or None

        sql = """
            SELECT workspace_id, MAX(is_default) AS is_default
            FROM (
                SELECT
                    wm.workspace_id AS workspace_id,
                    COALESCE(wm.is_default, 0) AS is_default
                FROM workspace_membership wm
                JOIN workspace w
                  ON w.id = wm.workspace_id
                 AND COALESCE(w.is_active, 1) = 1
                WHERE wm.user_id = :user_id
                  AND COALESCE(wm.is_active, 1) = 1
                  AND (:scope_workspace_id IS NULL OR wm.workspace_id = :scope_workspace_id)

                UNION ALL

                SELECT
                    w.id AS workspace_id,
                    0 AS is_default
                FROM organization_membership om
                JOIN organization o
                  ON o.id = om.organization_id
                 AND COALESCE(o.is_active, 1) = 1
                JOIN workspace w
                  ON w.organization_id = om.organization_id
                 AND COALESCE(w.is_active, 1) = 1
                WHERE om.user_id = :user_id
                  AND COALESCE(om.is_active, 1) = 1
                  AND (:scope_workspace_id IS NULL OR w.id = :scope_workspace_id)
        """
        if include_all_workspaces:
            sql += """

                UNION ALL

                SELECT
                    w.id AS workspace_id,
                    0 AS is_default
                FROM workspace w
                WHERE COALESCE(w.is_active, 1) = 1
                  AND (:scope_workspace_id IS NULL OR w.id = :scope_workspace_id)
            """

        sql += """
            ) access_rows
            GROUP BY workspace_id
            ORDER BY is_default DESC, workspace_id ASC
        """
        try:
            result = self._sql.execute_query_mappings(
                sql,
                {"user_id": user_id, "scope_workspace_id": scope_workspace_value},
            )
            rows = [dict(row) for row in result]
            if not rows:
                return []
            has_default = any(bool(row.get("is_default")) for row in rows)
            if not has_default:
                rows[0]["is_default"] = True
                for row in rows[1:]:
                    row["is_default"] = False
            else:
                seen_default = False
                for row in rows:
                    if bool(row.get("is_default")) and not seen_default:
                        row["is_default"] = True
                        seen_default = True
                    else:
                        row["is_default"] = False
            return rows
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Failed to retrieve user workspaces: {str(e)}", 500)

    def _user_is_visible_in_workspace(self, user_id: str, workspace_id: str) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT 1
            FROM workspace_membership wm
            WHERE wm.user_id = :user_id
              AND wm.workspace_id = :workspace_id
              AND COALESCE(wm.is_active, 1) = 1

            UNION ALL

            SELECT 1
            FROM workspace w
            JOIN organization_membership om
              ON om.organization_id = w.organization_id
             AND om.user_id = :user_id
             AND COALESCE(om.is_active, 1) = 1
            WHERE w.id = :workspace_id
              AND COALESCE(w.is_active, 1) = 1
            LIMIT 1
            """,
            {"user_id": str(user_id or "").strip(), "workspace_id": str(workspace_id or "").strip()},
        )
        return bool(rows)

    def _get_user_workspaces_bulk(self, user_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for uid in user_ids or []:
            out[str(uid)] = self.get_user_workspaces(str(uid))
        return out
    
    validate_params("user_id", "workspace_id")
    def delete_user_workspace(self, user_id: str, workspace_id: str) -> Dict[str, str]:
        """
        Deletes the user to workspace relationship

        :param user_id: The user ID
        :type user_id: str
        :param workspace_id: The ID of the workspace
        :type workspace_id: str

        Returns:
            Dict[str, str]: Success Message
        Raises:
            ForgeError 500 (database error)
        """

        sql = "DELETE FROM workspace_membership WHERE user_id = :user_id AND workspace_id = :workspace_id"
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {"user_id": user_id, "workspace_id": workspace_id})
            return {"message": "Mapping deleted successfully"}
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Failed to map user to workspace: {str(e)}", 500)

    validate_params("username")
    def check_for_existing_user(self, username: str) -> bool:
        """
        Checks to see if the username exists in the database.
        
        :param username: The username
        :type username: str

        Returns:
            bool: True if the user exists
        Raises:
            ForgeError 500 (database error)

        """
        sql = "SELECT * FROM users WHERE username = :username"
        try:
            logging.info(F"Checking for existing user: {username}")
            result = self._sql.execute_query_mappings(sql, {"username": username})

            if len(result) > 0:
                logging.info(f"User {username} exists.")
                return True
            else:
                logging.info(f"User {username} does not exist.")
                return False
                
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ForgeError(f"Failed to retrieve user workspaces: {str(e)}", 500)

    def _map_user_row(self, base_row: Dict[str, Any]) -> User:
        user_data = {
            "user_id": base_row["user_id"],
            "user_name": base_row.get("username"),
            "password": base_row.get("password"),
            "first_name": base_row.get("first_name"),
            "last_name": base_row.get("last_name"),
            "email": base_row.get("email"),
            "status": base_row.get("user_status"),
            "tos_accepted": base_row.get("tos_accepted"),
            "eula_accepted": base_row.get("eula_accepted"),
            "otp_secret": base_row.get("otp_secret"),
            "two_factor_preference": base_row.get("two_factor_preference"),
         
            "last_log_in": base_row.get("last_log_in")
        }
        return User(**user_data, workspaces=[])

    @staticmethod
    def _to_role_models(rows: List[Dict[str, Any]]) -> List[Role]:
        out: List[Role] = []
        seen = set()
        for row in rows or []:
            role_id = str(row.get("role_id") or "").strip()
            role_name = str(row.get("role_name") or "").strip()
            if not role_id or not role_name:
                continue
            if role_id in seen:
                continue
            seen.add(role_id)
            out.append(Role(role_id=role_id, role_name=role_name))
        return out

    def update_last_login(self, user_id: str):
        sql = """
            UPDATE users
            SET last_log_in = :now
            WHERE user_id = :user_id
        """

        with self._sql.transaction() as tx:
            tx.execute_write(sql, {"now": datetime.now(timezone.utc), "user_id": user_id})

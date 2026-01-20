import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import exc
from werkzeug.security import generate_password_hash

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.models.product import Product
from app.models.product_role import ProductRole
from app.models.role import Role
from app.models.status_enum import UserStatus
from app.models.user import User
from app.models.user_invitation import UserInvitation
from app.models.user_workspace import Workspace
from app.ports.sql_executor import SQLExecutor, SQLTransaction
from app.services.password_service import generate_otp_secret
from app.utils.password_check import is_good_password

logger = logging.getLogger(__name__)

class UserService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

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
            raise ServiceError(f"Database error: {str(e)}", 500)
    def get_counts(self):
        sql = """
            SELECT status, COUNT(*) as count
            FROM users WHERE status is not null
            GROUP BY status
        """

        try:
            results = self._sql.execute_query_mappings(sql)
            counts = {row["status"]: row["count"] for row in results}
            counts["All"] = sum(counts.values())

            for status in UserStatus:
                counts.setdefault(status.value, 0)

            return counts
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
    
    validate_params("email")
    def resend_invite(self, user_id:str, email: str):
        from app.tasks.email_tasks import send_invite_email_task
        send_invite_email_task.delay(email, user_id)
        self.update_last_login(user_id)
        return {"email": email, "user_id": user_id}
    
    validate_params("emails", "product_roles", "workspaces")
    def create_invite_bulk(self, emails: List[str], products: List[dict], workspaces: List[dict]):
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

                    # map workspaces (first one default = True)
                    for workspace in workspaces:
                        self.map_user_workspace(user_id, workspace["workspace_id"], workspace["is_default"], tx)

                    # map product roles
                    for p in products:
                        self.map_user_product(user_id, p["product_id"], tx)
                        self.map_user_product_role(user_id, p["product_role_id"], tx)

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
            raise ServiceError(f"Database error: {str(e)}", 500)

    validate_params("email")
    def create_invite(self, invitation: UserInvitation) -> Dict[str, str]:
        if self.check_for_existing_user(invitation.email):
            logger.error(f"User with this username or email already exists: {invitation.email}")
            raise ServiceError("User with this email already exists", 409)

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
                
                for product in invitation.products:
                    self.map_user_product(user_id, product.product_id, tx)

                    for r in product.roles:
                        self.map_user_product_role(user_id, r.product_role_id, tx)
                
                logger.info(f"User {invitation.email} created successfully")

                from app.tasks.email_tasks import send_invite_email_task
                send_invite_email_task.delay(invitation.email, user_id)

                return {"email": invitation.email, "user_id": user_id}
        except exc.IntegrityError:
            logger.error(f"User with this username or email already exists: {invitation.email}")
            raise ServiceError("User with this username or email already exists", 409)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
                    
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
            ServiceError 409 (duplicate user), 500 (database error)
        """
        if self.check_for_existing_user(username):
            logger.error(f"User with this username or email already exists: {username}")
            raise ServiceError("User with this username already exists", 409)

        if not is_good_password(password=password):
            logger.error(f"User {username} in violation of password rules - need a new password.")
            raise ServiceError("Password violates policy rules.", 409)
        

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
            raise ServiceError("User with this username or email already exists", 409)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)

    validate_params("user_id")

    def update_user(self, user_id: str, update_data: "User") -> Dict[str, Any]:
            """
            Updates a user and synchronizes related workspaces and product roles.
            Expects update_data to optionally include:
            - workspaces: List[{"workspace_id": str|int, "is_default": bool}]
            - products:   List[{"product_id": str, "roles": [{"product_role_id": str, ...}], ...}]
            """
            # 1) Load current user (and fail fast if missing)
            current_user = self.get_user(user_id)
            if not current_user:
                raise ServiceError(f"User with ID {user_id} not found", 404)

            # 2) Prepare scalar field updates on the users table, excluding nested relations
            update_fields = update_data.model_dump(exclude_unset=True)
            new_workspaces = update_fields.pop("workspaces", None)
            new_products   = update_fields.pop("products", None)

            params = {"user_id": user_id}
            updates = []

            for field, new_value in update_fields.items():
                if field == "display_name":
                    continue
                current_value = getattr(current_user, field, None)

                if field == "password" and new_value:
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

                    # 3c) Sync product roles junction if provided
                    if new_products is not None:
                        self._sync_user_product_roles(tx, user_id, new_products)

                # 4) Return fresh copy
                return self.get_user(user_id)

            except exc.SQLAlchemyError as e:
                logger.error(f"update_user failed for {user_id}: {e}")
                raise ServiceError(f"Failed to update user: {str(e)}", 500)


    def _sync_user_workspaces(self, tx: SQLTransaction, user_id: str, new_ws: List[Dict[str, Any]]) -> None:
        """
        new_ws: [{"workspace_id": "...", "is_default": bool}, ...]
        """
        # Normalize desired map: id -> is_default
        desired = {
            str(w["workspace_id"]): bool(w.get("is_default", False))
            for w in (new_ws or [])
        }

        # Load existing
        rows = tx.execute_query_mappings(
            "SELECT workspace_id, is_default FROM user_workspace_map WHERE user_id = :uid",
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
                f"DELETE FROM user_workspace_map WHERE user_id = :uid AND workspace_id IN ({placeholders})",
                params,
            )

        # Insert new
        if to_insert:
            tx.execute_write(
                "INSERT INTO user_workspace_map (user_id, workspace_id, is_default) "
                "VALUES (:uid, :workspace_id, :is_default)",
                [
                    {"uid": user_id, "workspace_id": wid, "is_default": desired[wid]}
                    for wid in to_insert
                ],
            )

        # Update flags where changed
        for wid in to_update:
            tx.execute_write(
                "UPDATE user_workspace_map "
                "SET is_default = :is_default "
                "WHERE user_id = :uid AND workspace_id = :workspace_id",
                {"uid": user_id, "workspace_id": wid, "is_default": desired[wid]},
            )
        if any(desired.values()):
            # keep only the first True as default
            true_ids = [wid for wid, is_def in desired.items() if is_def]
            keep = true_ids[0]
            if len(true_ids) > 1:
                tx.execute_write(
                    "UPDATE user_workspace_map SET is_default = 0 "
                    "WHERE user_id = :uid AND workspace_id != :keep",
                    {"uid": user_id, "keep": keep},
                )

    def _sync_user_product_roles(self, tx: SQLTransaction, user_id: str, new_products: List[Dict[str, Any]]) -> None:
        """
        new_products: [{"product_id": "...", "roles": [{"product_role_id": "..."}]}...]
        We only need the set of product_role_id assignments for the user.
        """
        desired_role_ids = set()
        for p in (new_products or []):
            for r in (p.get("roles") or []):
                prid = r.get("product_role_id")
                if prid:
                    desired_role_ids.add(str(prid))

        # Load existing assignments
        rows = tx.execute_query_mappings(
            "SELECT product_role_id FROM user_roles WHERE user_id = :uid",
            {"uid": user_id},
        )
        existing_role_ids = set(str(r["product_role_id"]) for r in rows)

        to_delete = existing_role_ids - desired_role_ids
        to_insert = desired_role_ids - existing_role_ids

        if to_delete:
            ids_list = list(to_delete)
            placeholders = ",".join([f":id{i}" for i in range(len(ids_list))])
            params = {"uid": user_id, **{f"id{i}": rid for i, rid in enumerate(ids_list)}}
            tx.execute_write(
                f"DELETE FROM user_roles WHERE user_id = :uid AND product_role_id IN ({placeholders})",
                params,
            )

        if to_insert:
            tx.execute_write(
                "INSERT INTO user_roles (user_id, product_role_id) "
                "VALUES (:uid, :product_role_id)",
                [{"uid": user_id, "product_role_id": prid} for prid in to_insert],
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
            ServiceError 404 (User not found), 500 (database error)
        """
        delete_user = "DELETE FROM users WHERE user_id = :user_id"
        delete_user_workspace = "DELETE FROM user_workspace_map WHERE user_id = :user_id"

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(delete_user_workspace, {"user_id": user_id})
                result = tx.execute_write(delete_user, {"user_id": user_id})
                if (result or 0) == 0:
                    logger.error(f"User not found: {user_id}")
                    raise ServiceError("User not found", 404)
            return {"message": "User deleted successfully"}
        except exc.SQLAlchemyError as e:
            logger.error(f"{str(e)}")
            raise ServiceError(f"Failed to delete user: {str(e)}", 500)

    @validate_params("username")
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Fetches a user by username.
        
        :parm username: The username for the user.
        :type username: str

        Returns:
            dict[str, any]: User
        Raises:
            ServiceError 404 (User not found), 500 (database error)
        """
        sql = """
            SELECT u.user_id, u.username, u.password, u.email, u.first_name, u.last_name, u.tos_accepted, u.eula_accepted, u.status as user_status,
                u.otp_secret, u.last_log_in, u.two_factor_preference, orgs.workspace_id, orgs.is_default, p.product_name, p.status as product_status, p.last_update,
                ur.product_role_id, r.role_name, r.role_id
            FROM users u
            LEFT JOIN user_workspace_map orgs on orgs.user_id = u.user_id
            LEFT JOIN user_roles ur on ur.user_id = u.user_id
            LEFT JOIN product_roles pr on pr.product_role_id = ur.product_role_id
            LEFT JOIN products p on p.product_id = pr.product_id
            LEFT JOIN roles r on r.role_id = pr.role_id
            WHERE u.username = :username AND p.status not in ('Inactive');
        """
        try:
            result = self._sql.execute_query_mappings(sql, {"username": username})
            if not result:
                logger.error(f"User not found {username}")
                raise ServiceError("User not found", 404)
            return self.map_user_with_products(result)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Failed to retrieve user: {str(e)}", 500)

    @validate_params("user_id")
    def get_user(self, user_id: str) -> Optional[User]:
        """
        Fetches a user by user_id.
        
        :parm user_id: The user_id for the user.
        :type user_id: str

        Returns:
            dict[str, any]: User
        Raises:
            ServiceError 404 (User not found), 500 (database error)
        """
        sql = """
            SELECT u.user_id, u.username, u.password, u.email, u.first_name, u.last_name, u.tos_accepted, u.eula_accepted, u.status as user_status,
                u.otp_secret, u.last_log_in, u.two_factor_preference, orgs.workspace_id, orgs.is_default, p.product_name, p.product_id,
                p.status as product_status, p.last_update, ur.product_role_id, r.role_name, r.role_id
            FROM users u
            LEFT JOIN user_workspace_map orgs on orgs.user_id = u.user_id
            LEFT JOIN user_roles ur on ur.user_id = u.user_id
            LEFT JOIN product_roles pr on pr.product_role_id = ur.product_role_id
            LEFT JOIN products p on p.product_id = pr.product_id
            LEFT JOIN roles r on r.role_id = pr.role_id
            WHERE u.user_id = :user_id AND p.status not in ('Inactive');
        """
        try:
            result = self._sql.execute_query_mappings(sql, {"user_id": user_id})
            if not result:
                logger.error(f"User not found {user_id}")
                raise ServiceError("User not found", 404)
            return self.map_user_with_products(result)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Failed to retrieve user: {str(e)}", 500)
    

    def get_users(self, status: str = 'All', cursor: Optional[str] = None, limit: int = 10, direction: str = 'forward', username: Optional[str] = None) -> tuple:
        where_clause = "status = :status OR :status = 'All' AND status is not null"
        params = {"status": status, "limit": limit + 1}  # One extra for pagination check

        if username:
            where_clause += " AND username like :username"
            params["username"] = f"{username}%"

        if cursor:
            if direction == 'forward':
                where_clause += " AND user_id > :cursor"
                params["cursor"] = cursor
                order_by = "ORDER BY user_id ASC"
            else:
                where_clause += " AND user_id < :cursor"
                params["cursor"] = cursor
                order_by = "ORDER BY user_id ASC"  # Reverse later
        else:
            order_by = "ORDER BY user_id ASC"

        base_user_query = f"""
            SELECT user_id, username, password, first_name, last_name, email, status, tos_accepted, 
                eula_accepted, otp_secret, two_factor_preference, last_log_in
            FROM users
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

        # Get product and workspace data for all users in this page
        user_ids_placeholders = ",".join([f":uid{i}" for i in range(len(user_ids))])
        extended_query = """
            SELECT u.user_id, orgs.workspace_id, orgs.is_default, p.product_id, p.product_name, p.product_id, p.status, p.last_update,
                ur.product_role_id, r.role_id, r.role_name
            FROM users u
            LEFT JOIN user_workspace_map orgs ON orgs.user_id = u.user_id
            LEFT JOIN user_roles ur ON ur.user_id = u.user_id
            LEFT JOIN product_roles pr ON pr.product_role_id = ur.product_role_id
            LEFT JOIN products p ON p.product_id = pr.product_id
            LEFT JOIN roles r ON r.role_id = pr.role_id
            WHERE p.status not in ('Inactive') AND u.user_id IN ({user_ids_placeholders})
        """

        extended_rows = self._sql.execute_query_mappings(
            extended_query.format(user_ids_placeholders=user_ids_placeholders),
            {f"uid{i}": uid for i, uid in enumerate(user_ids)},
        )

        # Group extended rows by user_id
        user_map = defaultdict(lambda: {"products": defaultdict(list), "workspaces": []})
        for row in extended_rows:
            uid = row["user_id"]

            # Workspaces
            if row["workspace_id"]:
                workspace = Workspace(
                    workspace_id=row["workspace_id"],
                    is_default=row.get("is_default", False)
                )
                if workspace not in user_map[uid]["workspaces"]:
                    user_map[uid]["workspaces"].append(workspace)

            # Products
            if row["product_id"] and row["product_role_id"] and row["role_id"]:
                role = Role(role_id=row["role_id"], role_name=row["role_name"])
                product_role = ProductRole(product_role_id=row["product_role_id"], role=role)
                user_map[uid]["products"][row["product_id"], row["product_name"], row["status"], row["last_update"]].append(product_role)

        # Build full user models
        users = []
        for base_row in trimmed:
            uid = base_row["user_id"]
            row_dict = dict(base_row)
            row_dict['tos_accepted'] = bool(row_dict.get('tos_accepted'))
            row_dict['eula_accepted'] = bool(row_dict.get('eula_accepted'))

            # Products
            products = [
                Product(
                    product_id=pid,
                    product_name=pname,
                    status=status,
                    last_update=last_update,
                    roles=proles
                )
                for (pid, pname, status, last_update), proles in user_map[uid]["products"].items()
            ]

            # Workspaces
            workspaces = list(user_map[uid]["workspaces"])

            users.append(User(**row_dict, products=products, workspaces=workspaces))

        # Pagination cursors
        next_cursor = None
        prev_cursor = None

        if len(base_rows) > limit:
            next_cursor = base_rows[limit - 1]["user_id"]
        if direction == 'forward' and cursor:
            prev_query = "SELECT user_id FROM users WHERE user_id < :cursor AND (:status = 'All' OR status = :status) ORDER BY user_id DESC LIMIT 1"
            prev_rows = self._sql.execute_query_mappings(prev_query, {"cursor": cursor, "status": status})
            prev_result = prev_rows[0] if prev_rows else None
            if prev_result:
                prev_cursor = prev_result['user_id']
        elif direction == 'backward' and len(users) > 0:
            next_cursor = users[0].user_id
            users = users[::-1]
            prev_query = "SELECT user_id FROM users WHERE user_id < :cursor AND (:status = 'All' OR status = :status) ORDER BY user_id DESC LIMIT 1"
            prev_rows = self._sql.execute_query_mappings(prev_query, {"cursor": users[0].user_id, "status": status})
            prev_result = prev_rows[0] if prev_rows else None
            if prev_result:
                prev_cursor = prev_result['user_id']

        count_query = "SELECT COUNT(*) as count FROM users WHERE :status = 'All' OR status = :status"
        count_rows = self._sql.execute_query_mappings(count_query, {"status": status})
        total_count = count_rows[0].get("count") if count_rows else 0

        return users, next_cursor, prev_cursor, total_count


    @validate_params("user_id", "workspace_id")
    def map_user_workspace(
        self,
        user_id: str,
        workspace_id: str,
        is_default: bool,
        tx: Optional[SQLTransaction] = None,
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
            ServiceError: On duplicate or SQL failure.
        """
        mapping = self.get_user_workspaces(user_id)

        if any(w['workspace_id'] == workspace_id for w in mapping):
            logger.error(f"User: {user_id} already mapped to workspace {workspace_id}")
            raise ServiceError("Mapping already exists for user", 409)

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
                    UPDATE user_workspace_map
                    SET is_default = false
                    WHERE user_id = :user_id AND is_default = true
                """
                tx.execute_write(update_sql, {"user_id": user_id})

            insert_sql = """
                INSERT INTO user_workspace_map (user_id, workspace_id, is_default)
                VALUES (:user_id, :workspace_id, :is_default)
            """
            tx.execute_write(
                insert_sql,
                {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "is_default": is_default,
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
            raise ServiceError(f"Failed to map user to workspace: {str(e)}", 500)
    
    @validate_params("user_id", "product")
    def map_user_product(self, user_id: str, product: str, tx: Optional[SQLTransaction] = None):
        mapping = self.get_user_products(user_id)

        if any(p['product_id'] == product for p in mapping):
            return None
        

        try:
            if tx is None:
                with self._sql.transaction() as local_tx:
                    return self.map_user_product(user_id, product, local_tx)

            sql = "INSERT INTO user_product_map (user_id, product_id) VALUES(:user_id, :product_id)"
            tx.execute_write(sql, {"user_id": user_id, "product_id": product})

            return {
                "message": "User and product mapped successfully",
                "mapping": {
                    "user_id": user_id,
                    "product_id": product,
                },
            }

        except exc.SQLAlchemyError as e:
            logger.error(f"SQL error during user mapping: {str(e)}")
            raise ServiceError(f"Failed to map user to product: {str(e)}", 500)

    @validate_params("user_id", "product_role_id")
    def map_user_product_role(self, user_id: str, product_role_id: str, tx: Optional[SQLTransaction] = None):
        mapping = self.get_user_product_roles(user_id)

        if any(p['product_role_id'] == product_role_id for p in mapping):
            return None
        

        try:
            if tx is None:
                with self._sql.transaction() as local_tx:
                    return self.map_user_product_role(user_id, product_role_id, local_tx)

            sql = "INSERT INTO user_roles (user_role_id, user_id, product_role_id) VALUES(null, :user_id, :product_role_id)"
            tx.execute_write(sql, {"user_id": user_id, "product_role_id": product_role_id})

            return {
                "message": "User and role mapped successfully",
                "mapping": {
                    "user_id": user_id,
                    "product_role_id": product_role_id,
                },
            }

        except exc.SQLAlchemyError as e:
            logger.error(f"SQL error during user mapping: {str(e)}")
            raise ServiceError(f"Failed to map user to product: {str(e)}", 500)

    @validate_params("user_id")
    def get_user_product_roles(self, user_id: str):
        sql = """ 
            SELECT u.product_role_id, r.role_name, r.role_id
            FROM user_roles u
            LEFT JOIN product_roles pr on pr.product_role_id = u.product_role_id
            LEFT JOIN roles r on r.role_id = pr.role_id
            LEFT JOIN products p on p.product_id = pr.product_id
            WHERE user_id = :user_id AND p.status not in ('Inactive')
        """

        try:
            results = self._sql.execute_query_mappings(sql, {"user_id": user_id})
            return [dict(row) for row in results]
        except exc.SQLAlchemyError as e:
            logger.error(f"Error fetching roles for user_id={user_id}: {str(e)}")
            raise ServiceError(f"Failed to retrieve user roles: {str(e)}", 500)

    @validate_params("user_id")
    def get_user_products(self, user_id: str):
        sql = """
            SELECT p.product_id, p.product_name 
            FROM user_product_map upm 
            JOIN products p ON upm.product_id = p.product_id 
            WHERE user_id = :user_id AND p.status not in ('Inactive')
        """

        try:
            results = self._sql.execute_query_mappings(sql, {"user_id": user_id})
            return [dict(row) for row in results]
        except exc.SQLAlchemyError as e:
            logger.error(f"Error fetching products for user_id={user_id}: {str(e)}")
            raise ServiceError(f"Failed to retrieve user products: {str(e)}", 500)

    

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
            raise ServiceError("Workspace mapping not found for user", 404)

        if current_mapping['is_default'] and not is_default:
            raise ServiceError("User must always have a default workspace", 409)

        sql = """
            UPDATE user_workspace_map 
            SET is_default = :is_default 
            WHERE user_id = :user_id AND workspace_id = :workspace_id
        """

        try:
            with self._sql.transaction() as tx:
                if is_default:
                    # Unset previous default
                    unset_sql = """
                        UPDATE user_workspace_map
                        SET is_default = false
                        WHERE user_id = :user_id AND is_default = true
                    """
                    tx.execute_write(unset_sql, {"user_id": user_id})

                tx.execute_write(
                    sql,
                    {"user_id": user_id, "workspace_id": workspace_id, "is_default": is_default},
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
            raise ServiceError(f"Failed to update workspace mapping: {str(e)}", 500)

    @validate_params("user_id")
    def get_user_workspaces(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all workspaces for a given user in a single query.
        
        :param user_id: The user ID
        :type user_id: str

        Returns:
            Dict[str, any]: Success Message
        Raises:
            ServiceError 500 (database error)

        """
        sql = """
            SELECT workspace_id, is_default
            FROM user_workspace_map uwm
            WHERE user_id = :user_id
        """
        try:
            result = self._sql.execute_query_mappings(sql, {"user_id": user_id})
            return [dict(row) for row in result]
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Failed to retrieve user workspaces: {str(e)}", 500)
    
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
            ServiceError 500 (database error)
        """

        sql = "DELETE FROM user_workspace_map WHERE user_id = :user_id AND workspace_id = :workspace_id"
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {"user_id": user_id, "workspace_id": workspace_id})
            return {"message": "Mapping deleted successfully"}
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Failed to map user to workspace: {str(e)}", 500)

    validate_params("username")
    def check_for_existing_user(self, username: str) -> bool:
        """
        Checks to see if the username exists in the database.
        
        :param username: The username
        :type username: str

        Returns:
            bool: True if the user exists
        Raises:
            ServiceError 500 (database error)

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
            raise ServiceError(f"Failed to retrieve user workspaces: {str(e)}", 500)

    def map_user_with_products(self, rows: List[dict]) -> User:
        if not rows:
            raise ValueError("No data returned from query")

        base_row = rows[0]
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

        # Group products and roles
        product_map = {}

        for row in rows:
            # Expect these columns from your SQLAlchemy row:
            # row["product_id"], row["product_name"], row["product_role_id"],
            # row["role_id"], row["role_name"]
            pid = row.get("product_id")
            pname = row.get("product_name")
            last_update = row.get("last_update")
            prod_role_id = row.get("product_role_id")
            product_status = row.get("product_status")
            role_id = row.get("role_id")
            role_name = row.get("role_name")

            # Skip incomplete rows
            if not (pid and pname and prod_role_id and role_name):
                continue

            # init bucket
            if pid not in product_map:
                product_map[pid] = {"name": pname, "status": product_status, "last_update": last_update, "roles": [], "seen": set()}

            # de-dupe product roles per product
            if prod_role_id in product_map[pid]["seen"]:
                continue

            role = Role(
                role_id=role_id,
                role_name=role_name
            )
            product_role = ProductRole(
                product_role_id=prod_role_id,
                role=role
            )

            product_map[pid]["roles"].append(product_role)
            product_map[pid]["seen"].add(prod_role_id)

        # build Products
        products = [
            Product(
                product_id=pid,
                product_name=bucket["name"],
                status=bucket["status"],
                last_update=bucket["last_update"],
                roles=bucket["roles"]
            )
            for pid, bucket in product_map.items()
        ]

        workspaces = []
        seen_workspace_ids = set()
        for row in rows:
            org_id = row.get("workspace_id")
            if org_id and org_id not in seen_workspace_ids:
                workspaces.append(Workspace(
                    workspace_id=org_id,
                    is_default=row.get("is_default", False)
                ))
                seen_workspace_ids.add(org_id)

        return User(
            **user_data,
            products=products,
            workspaces=workspaces
        )

    def update_last_login(self, user_id: str):
        sql = """
            UPDATE users
            SET last_log_in = :now
            WHERE user_id = :user_id
        """

        with self._sql.transaction() as tx:
            tx.execute_write(sql, {"now": datetime.now(timezone.utc), "user_id": user_id})

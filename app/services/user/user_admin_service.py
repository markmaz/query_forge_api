from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, List

from sqlalchemy import exc
from werkzeug.security import generate_password_hash

from app.exceptions.forge_error import ForgeError
from app.models.tenancy.user_workspace import UserInvitation
from app.ports.sql_executor import ForgeQueryPort
from app.services.password_service import generate_otp_secret

if TYPE_CHECKING:
    from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class UserAdminService:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def update_status(self, service: "UserService", user_id: str, status: str) -> Dict[str, str]:
        sql = """
            UPDATE users set status = :status WHERE user_id = :user_id
        """
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {"user_id": user_id, "status": status})
            service.update_last_login(user_id)
            return {"message": "Status updated."}
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Database error: {str(err)}", 500) from err

    def resend_invite(self, service: "UserService", user_id: str, email: str) -> Dict[str, str]:
        from app.tasks.email_tasks import send_invite_email_task

        send_invite_email_task.delay(email, user_id)
        service.update_last_login(user_id)
        return {"email": email, "user_id": user_id}

    def create_invite_bulk(self, service: "UserService", emails: List[str], workspaces: List[dict]) -> Dict[str, Any]:
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

                    if (res or 0) == 0:
                        skipped_existing.append(email)
                        continue

                    user_id = params["user_id"]

                    for workspace in workspaces:
                        service.map_user_workspace(
                            user_id,
                            workspace["workspace_id"],
                            workspace["is_default"],
                            tx,
                        )

                    from app.tasks.email_tasks import send_invite_email_task

                    send_invite_email_task.delay(email, user_id)

                    invites_sent += 1

            return {
                "total_user_count": len(emails),
                "invites_sent": invites_sent,
                "users_skipped": len(skipped_existing),
                "skipped_emails": skipped_existing,
            }

        except exc.SQLAlchemyError as err:
            logger.error("create_invite_bulk failed: %s", err)
            raise ForgeError(f"Database error: {str(err)}", 500) from err

    def create_invite(self, service: "UserService", invitation: UserInvitation) -> Dict[str, str]:
        if service.check_for_existing_user(invitation.email):
            logger.error("User with this username or email already exists: %s", invitation.email)
            raise ForgeError("User with this email already exists", 409)

        sql = """
            INSERT INTO users (email, user_id, status, username, password, otp_secret, last_log_in)
            VALUES (:email, :user_id, :status, :email, '', :otp, CURRENT_TIMESTAMP)
        """
        user_id = str(uuid.uuid4())

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    sql,
                    {
                        "email": invitation.email,
                        "user_id": user_id,
                        "status": "Invited",
                        "otp": generate_otp_secret(),
                    },
                )

                for org in invitation.workspaces:
                    service.map_user_workspace(user_id, org.workspace_id, org.is_default, tx)

                logger.info("User %s created successfully", invitation.email)

                from app.tasks.email_tasks import send_invite_email_task

                send_invite_email_task.delay(invitation.email, user_id)

                return {"email": invitation.email, "user_id": user_id}
        except exc.IntegrityError as err:
            logger.error("User with this username or email already exists: %s", invitation.email)
            raise ForgeError("User with this username or email already exists", 409) from err
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Database error: {str(err)}", 500) from err

    def create_user(
        self,
        service: "UserService",
        username: str,
        password: str,
        email: str,
        first_name: str,
        last_name: str,
        *,
        password_validator,
    ) -> Dict[str, str]:
        if service.check_for_existing_user(username):
            logger.error("User with this username or email already exists: %s", username)
            raise ForgeError("User with this username already exists", 409)

        password_validator(password)

        hashed_password = generate_password_hash(password)
        user_id = str(uuid.uuid4())

        sql = """
            INSERT INTO users (username, password, email, user_id)
            VALUES (:username, :password, :email, :user_id)
        """
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    sql,
                    {
                        "username": username,
                        "password": hashed_password,
                        "email": email,
                        "user_id": user_id,
                        "first_name": first_name,
                        "last_name": last_name,
                    },
                )
                logger.info("User %s, %s created successfully", username, email)
            return {"username": username, "email": email, "user_id": user_id}
        except exc.IntegrityError as err:
            logger.error("User with this username or email already exists: %s, %s", username, email)
            raise ForgeError("User with this username or email already exists", 409) from err
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Database error: {str(err)}", 500) from err

    def delete_user(self, user_id: str) -> Dict[str, str]:
        delete_user = "DELETE FROM users WHERE user_id = :user_id"
        delete_user_workspace = "DELETE FROM workspace_membership WHERE user_id = :user_id"
        delete_user_org_membership = "DELETE FROM organization_membership WHERE user_id = :user_id"
        delete_user_roles = "DELETE FROM user_roles WHERE user_id = :user_id"
        delete_user_domain_mapping = "DELETE FROM user_domain_mapping WHERE user_id = :user_id"

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(delete_user_roles, {"user_id": user_id})
                tx.execute_write(delete_user_domain_mapping, {"user_id": user_id})
                tx.execute_write(delete_user_workspace, {"user_id": user_id})
                tx.execute_write(delete_user_org_membership, {"user_id": user_id})
                result = tx.execute_write(delete_user, {"user_id": user_id})
                if (result or 0) == 0:
                    logger.error("User not found: %s", user_id)
                    raise ForgeError("User not found", 404)
            return {"message": "User deleted successfully"}
        except exc.SQLAlchemyError as err:
            logger.error("%s", err)
            raise ForgeError(f"Failed to delete user: {str(err)}", 500) from err

import html
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import exc

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.config import SALES_INQUIRY_EMAIL
from app.email.mailer import get_logo, send_email
from app.ports.sql_executor import SQLExecutor

logger = logging.getLogger(__name__)


class SalesInquiryService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def _send_notification(self, inquiry_id: uuid.UUID, payload: Dict[str, Any]) -> None:
        if not SALES_INQUIRY_EMAIL:
            logger.info("Sales inquiry email not configured; skipping notification.")
            return

        def _esc(value: Any) -> str:
            return html.escape("" if value is None else str(value))

        subject = f"New Sales Inquiry ({_esc(payload.get('work_email'))})"
        html_body = "\n".join(
            [
                "<h2>New Sales Inquiry</h2>",
                f"<p><strong>ID:</strong> {_esc(inquiry_id)}</p>",
                f"<p><strong>Name:</strong> {_esc(payload.get('first_name'))} {_esc(payload.get('last_name'))}</p>",
                f"<p><strong>Work Email:</strong> {_esc(payload.get('work_email'))}</p>",
                f"<p><strong>Phone:</strong> {_esc(payload.get('phone'))}</p>",
                f"<p><strong>Organization:</strong> {_esc(payload.get('organization'))}</p>",
                f"<p><strong>Role Title:</strong> {_esc(payload.get('role_title'))}</p>",
                f"<p><strong>Primary Interest:</strong> {_esc(payload.get('primary_interest'))}</p>",
                f"<p><strong>Primary Data Model:</strong> {_esc(payload.get('primary_data_model'))}</p>",
                f"<p><strong>Problem Statement:</strong> {_esc(payload.get('problem_statement'))}</p>",
                f"<p><strong>Consent Contact:</strong> {_esc(payload.get('consent_contact'))}</p>",
                f"<p><strong>Source:</strong> {_esc(payload.get('source'))}</p>",
                f"<p><strong>IP Address:</strong> {_esc(payload.get('ip_address'))}</p>",
                f"<p><strong>User Agent:</strong> {_esc(payload.get('user_agent'))}</p>",
            ]
        )

        try:
            send_email(get_logo(), subject, SALES_INQUIRY_EMAIL, html_body)
        except Exception:
            logger.exception("Failed to send sales inquiry email notification.")

    def create_inquiry(self, payload: Dict[str, Any]) -> uuid.UUID:
        inquiry_id = uuid.uuid4()
        params = {
            "id": inquiry_id.bytes,
            "first_name": payload.get("first_name"),
            "last_name": payload.get("last_name"),
            "work_email": payload.get("work_email"),
            "phone": payload.get("phone"),
            "organization": payload.get("organization"),
            "role_title": payload.get("role_title"),
            "primary_interest": payload.get("primary_interest"),
            "primary_data_model": payload.get("primary_data_model"),
            "problem_statement": payload.get("problem_statement"),
            "consent_contact": int(bool(payload.get("consent_contact"))),
            "source": payload.get("source"),
            "ip_address": payload.get("ip_address"),
            "user_agent": payload.get("user_agent"),
        }

        sql = """
            INSERT INTO sales_inquiry (
                id,
                first_name,
                last_name,
                work_email,
                phone,
                organization,
                role_title,
                primary_interest,
                primary_data_model,
                problem_statement,
                consent_contact,
                source,
                ip_address,
                user_agent
            ) VALUES (
                :id,
                :first_name,
                :last_name,
                :work_email,
                :phone,
                :organization,
                :role_title,
                :primary_interest,
                :primary_data_model,
                :problem_statement,
                :consent_contact,
                :source,
                :ip_address,
                :user_agent
            )
        """

        try:
            self._sql.execute_write(sql, params)
        except exc.SQLAlchemyError:
            logger.exception("Failed to insert sales inquiry")
            raise

        self._send_notification(inquiry_id, payload)

        return inquiry_id

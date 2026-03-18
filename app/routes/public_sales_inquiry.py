import logging
import re
import time
from typing import Any, Dict, Optional

from flask import redirect, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.config import ERROR_SERVER_URL, ERROR_VALIDATION_URL, THANK_YOU_REDIRECT
from app.decorators.rbac import public
from app.services.sales_inquiry_service import SalesInquiryService

logger = logging.getLogger(__name__)

public_ns = Namespace("public", description="Public sales inquiry operations")

sales_inquiry_model = public_ns.model(
    "SalesInquiry",
    {
        "first_name": fields.String(required=True, description="First name"),
        "last_name": fields.String(required=True, description="Last name"),
        "work_email": fields.String(required=True, description="Work email"),
        "phone": fields.String(required=False, description="Phone number"),
        "organization": fields.String(required=True, description="Organization"),
        "role_title": fields.String(required=True, description="Role title"),
        "primary_interest": fields.String(required=True, description="Primary interest"),
        "primary_data_model": fields.String(required=True, description="Primary data model"),
        "problem_statement": fields.String(required=True, description="Problem statement"),
        "consent_contact": fields.Boolean(required=True, description="Consent to be contacted"),
        "source": fields.String(required=False, description="Submission source"),
    },
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FORM_TS_MIN_MS = 3000
_FORM_TS_MAX_MS = 2 * 60 * 60 * 1000


def _normalize_required_str(data: Dict[str, Any], field: str, errors: Dict[str, str]) -> Optional[str]:
    value = data.get(field)
    if value is None:
        errors[field] = "Required"
        return None
    if not isinstance(value, str):
        errors[field] = "Must be a string"
        return None
    value = value.strip()
    if not value:
        errors[field] = "Required"
        return None
    return value


def _normalize_optional_str(data: Dict[str, Any], field: str, errors: Dict[str, str]) -> Optional[str]:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        errors[field] = "Must be a string"
        return None
    value = value.strip()
    return value or None


def _normalize_consent(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("1", "on")
    return False


def _get_client_ip() -> Optional[str]:
    forwarded_for = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or None
    return request.remote_addr


@public_ns.route("/sales-inquiry")
class SalesInquiry(ForgeResource):
    @public_ns.expect(sales_inquiry_model, validate=False)
    @public_ns.doc(security=[])
    @public
    def post(self):
        data = request.form.to_dict(flat=True)
        if not data:
            return redirect(ERROR_VALIDATION_URL, code=303)

        honeypot = (data.get("website") or "").strip()
        if honeypot:
            return redirect(THANK_YOU_REDIRECT, code=303)

        form_ts = (data.get("form_ts") or "").strip()
        if form_ts:
            try:
                ts_ms = int(form_ts)
                now_ms = int(time.time() * 1000)
                delta = now_ms - ts_ms
                if delta < _FORM_TS_MIN_MS or delta > _FORM_TS_MAX_MS:
                    return redirect(THANK_YOU_REDIRECT, code=303)
            except ValueError:
                logger.debug("sales_inquiry: invalid form_ts")
        else:
            logger.debug("sales_inquiry: missing form_ts")

        errors: Dict[str, str] = {}
        first_name = _normalize_required_str(data, "first_name", errors)
        last_name = _normalize_required_str(data, "last_name", errors)
        work_email = _normalize_required_str(data, "work_email", errors)
        organization = _normalize_required_str(data, "organization", errors)
        role_title = _normalize_required_str(data, "role_title", errors)
        primary_interest = _normalize_required_str(data, "primary_interest", errors)
        primary_data_model = _normalize_required_str(data, "primary_data_model", errors)
        problem_statement = _normalize_required_str(data, "problem_statement", errors)
        phone = _normalize_optional_str(data, "phone", errors)
        source = _normalize_optional_str(data, "source", errors)

        consent_raw = data.get("consent_contact")
        consent_contact = _normalize_consent(consent_raw)
        if not consent_contact:
            errors["consent_contact"] = "Consent is required"

        if work_email and not _EMAIL_RE.match(work_email):
            errors["work_email"] = "Invalid email format"

        if errors:
            return redirect(ERROR_VALIDATION_URL, code=303)

        user_agent = request.headers.get("User-Agent")
        if user_agent:
            user_agent = user_agent[:255]

        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "work_email": work_email.lower(),
            "phone": phone,
            "organization": organization,
            "role_title": role_title,
            "primary_interest": primary_interest,
            "primary_data_model": primary_data_model,
            "problem_statement": problem_statement,
            "consent_contact": consent_contact,
            "source": source,
            "ip_address": _get_client_ip(),
            "user_agent": user_agent,
        }

        service = SalesInquiryService()
        try:
            service.create_inquiry(payload)
        except Exception:
            logger.exception("Sales inquiry insert failed")
            return redirect(ERROR_SERVER_URL, code=303)

        return redirect(THANK_YOU_REDIRECT, code=303)

from __future__ import annotations

from flask_restx import Namespace, fields


def _register_model(namespace: Namespace, name: str, model_spec: dict):
    existing = namespace.models.get(name)
    if existing is not None:
        return existing
    return namespace.model(name, model_spec)


def register_auth_models(namespace: Namespace) -> dict[str, object]:
    return {
        "login_model": _register_model(
            namespace,
            "Login",
            {
                "username": fields.String(required=True, description="Username"),
                "password": fields.String(required=True, description="Password"),
            },
        ),
        "invite_accept_model": _register_model(
            namespace,
            "InviteAcceptRequest",
            {
                "token": fields.String(required=False, description="Invite token (or use ?token=...)"),
                "first_name": fields.String(required=False),
                "last_name": fields.String(required=False),
                "password": fields.String(required=True),
                "email": fields.String(required=False, description="Must match invited email if provided"),
                "tos_accepted": fields.Boolean(required=False),
                "eula_accepted": fields.Boolean(required=False),
                "two_factor_preference": fields.String(required=False),
            },
        ),
        "totp_confirm_model": _register_model(
            namespace,
            "TotpConfirmRequest",
            {"code": fields.String(required=True, description="6-digit authenticator code")},
        ),
        "totp_verify_model": _register_model(
            namespace,
            "TotpVerifyRequest",
            {
                "challenge_id": fields.String(required=True, description="MFA login challenge id"),
                "code": fields.String(required=True, description="6-digit authenticator code"),
            },
        ),
        "totp_disable_model": _register_model(
            namespace,
            "TotpDisableRequest",
            {
                "password": fields.String(required=True, description="Current account password"),
                "code": fields.String(required=True, description="6-digit authenticator code"),
            },
        ),
    }


def register_public_models(namespace: Namespace) -> dict[str, object]:
    return {
        "sales_inquiry_model": _register_model(
            namespace,
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
    }

import logging
import os
from typing import Any, Dict

from flask import g, jsonify, make_response, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.config import COOKIE_SAMESITE, COOKIE_SECURE, REFRESH_COOKIE_PATH
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.status_enum import UserStatus
from app.models.tenancy.user import User
from app.services.auth import (
    LOGIN_CHALLENGE_TTL_S,
    LoginChallengeService,
    RateLimitService,
    TotpService,
)
from app.services.auth_service import AuthService, hash_token
from app.services.otp_service import OTP_CHALLENGE_TTL_S, issue_otp_challenge
from app.services.user_service import UserService
from app.utils.token_utils import validate_token

qf_auth_ns = Namespace('auth', description='Authentication operations')
logger = logging.getLogger(__name__)

MFA_VERIFY_MAX_ATTEMPTS = int(os.getenv("MFA_VERIFY_MAX_ATTEMPTS", "8"))
MFA_VERIFY_WINDOW_SECONDS = int(os.getenv("MFA_VERIFY_WINDOW_SECONDS", "300"))
MFA_CONFIRM_MAX_ATTEMPTS = int(os.getenv("MFA_CONFIRM_MAX_ATTEMPTS", "10"))
MFA_CONFIRM_WINDOW_SECONDS = int(os.getenv("MFA_CONFIRM_WINDOW_SECONDS", "600"))
MFA_DISABLE_MAX_ATTEMPTS = int(os.getenv("MFA_DISABLE_MAX_ATTEMPTS", "6"))
MFA_DISABLE_WINDOW_SECONDS = int(os.getenv("MFA_DISABLE_WINDOW_SECONDS", "600"))

login_model = qf_auth_ns.model('Login', {
    'username': fields.String(required=True, description="Username"),
    'password': fields.String(required=True, description="Password")
})

invite_accept_model = qf_auth_ns.model(
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
)

totp_confirm_model = qf_auth_ns.model(
    "TotpConfirmRequest",
    {
        "code": fields.String(required=True, description="6-digit authenticator code"),
    },
)

totp_verify_model = qf_auth_ns.model(
    "TotpVerifyRequest",
    {
        "challenge_id": fields.String(required=True, description="MFA login challenge id"),
        "code": fields.String(required=True, description="6-digit authenticator code"),
    },
)

totp_disable_model = qf_auth_ns.model(
    "TotpDisableRequest",
    {
        "password": fields.String(required=True, description="Current account password"),
        "code": fields.String(required=True, description="6-digit authenticator code"),
    },
)


def _extract_default_workspace_id(user: Any) -> str | None:
    workspaces = getattr(user, "workspaces", None) or []
    default_ws = next((w for w in workspaces if getattr(w, "is_default", False)), None)
    workspace_id = getattr(default_ws, "workspace_id", None)
    if workspace_id is None:
        return None
    return str(workspace_id)


def _extract_invite_token(body: Dict[str, Any]) -> str:
    body_token = str((body or {}).get("token") or "").strip()
    if body_token:
        return body_token
    return str(request.args.get("token") or "").strip()

@qf_auth_ns.route('/auth')
@qf_auth_ns.expect(login_model)
class Authenticate(ForgeResource):
    def post(self):
        data = request.json
        username = data.get("username")
        password = data.get("password")

        auth = AuthService()
        user = auth.non_interactive_authentication(username, password)

        if not user:
            return {"message": "Invalid username or password"}, 401

        tokens = auth.issue_tokens(user)
        workspace_id = _extract_default_workspace_id(user)
        response = make_response(
            jsonify(
                {
                    "access_token": tokens["access_token"],
                    "token_type": "Bearer",
                    "expires_in": tokens["expires_in"],
                    "token": tokens["access_token"],
                    "workspace_id": workspace_id,
                    "workspaceId": workspace_id,
                }
            )
        )
        response.set_cookie(
            "refresh_token",
            tokens["refresh_token"],
            httponly=True,
            secure=bool(COOKIE_SECURE),
            samesite=COOKIE_SAMESITE,
            max_age=auth.qf_refresh_ttl,
            path=REFRESH_COOKIE_PATH,
        )
        return response

@qf_auth_ns.route('/login')
@qf_auth_ns.expect(login_model)
class Login(ForgeResource):
    @qf_auth_ns.expect(login_model)
    @qf_auth_ns.response(code=200, description="Credentials accepted and OTP challenge issued")
    @qf_auth_ns.doc(security=[])
    @qf_auth_ns.doc(
        description=(
            "## Authentication\n"
            "This endpoint validates username and password, then starts an OTP challenge. "
            "It does not return JWT tokens directly.\n\n"
            "**Required URL Parameters:**\n"
            "- `username`: The username for the application.\n"
            "- `password`: The password for the application\n\n"
            "**Response Codes:**\n"
            "- `200`: Credentials accepted and OTP challenge metadata returned.\n"
            "- `401`: Invalid username or password"
        )
    )
    def post(self):
        """Step 1: credential authentication and OTP challenge issuance"""
        data = request.get_json(silent=True) or {}
        username = data.get("username")
        password = data.get("password")

        auth = AuthService()
        user = auth.authenticate(username, password)
        if not user:
            return {"message": "Invalid username or password"}, 401

        user_id = str(user["user_id"])
        if TotpService().is_totp_enabled(user_id):
            challenge_id = LoginChallengeService().create_challenge(user_id)
            logger.info("mfa_event=totp_login_challenge user_id=%s challenge_id=%s", user_id, challenge_id)
            workspace_id = str(user.get("workspace_id") or user.get("workspaceId") or "").strip() or None
            return jsonify(
                {
                    "mfa_required": True,
                    "mfa_type": "totp",
                    "challenge_id": challenge_id,
                    "challenge_expires_in": LOGIN_CHALLENGE_TTL_S,
                    "workspace_id": workspace_id,
                    "workspaceId": workspace_id,
                }
            )

        challenge_id = issue_otp_challenge(
            user_id=user_id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
        workspace_id = str(user.get("workspace_id") or user.get("workspaceId") or "").strip() or None
        return jsonify(
            {
                "requires_otp": True,
                "challenge_id": challenge_id,
                "challenge_expires_in": OTP_CHALLENGE_TTL_S,
                "workspace_id": workspace_id,
                "workspaceId": workspace_id,
            }
        )


@qf_auth_ns.route("/mfa/totp/start")
class StartTotpEnrollment(ForgeResource):
    @token_required
    def post(self):
        user_id = str(getattr(g, "user_id", "") or "").strip()
        payload = TotpService().start_totp_enrollment(user_id)
        return payload, 200


@qf_auth_ns.route("/mfa/totp/confirm")
class ConfirmTotpEnrollment(ForgeResource):
    @qf_auth_ns.expect(totp_confirm_model, validate=False)
    @token_required
    def post(self):
        user_id = str(getattr(g, "user_id", "") or "").strip()
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "").strip()
        if not code:
            return {"error": "code is required"}, 400

        RateLimitService().enforce(
            scope="mfa:totp:confirm",
            identifier=user_id,
            max_attempts=MFA_CONFIRM_MAX_ATTEMPTS,
            window_s=MFA_CONFIRM_WINDOW_SECONDS,
        )
        result = TotpService().confirm_totp_enrollment(user_id, code)
        return result, 200


@qf_auth_ns.route("/mfa/totp/verify")
class VerifyTotpChallenge(ForgeResource):
    @qf_auth_ns.expect(totp_verify_model, validate=False)
    @qf_auth_ns.doc(security=[])
    def post(self):
        data = request.get_json(silent=True) or {}
        challenge_id = str(data.get("challenge_id") or "").strip()
        code = str(data.get("code") or "").strip()
        if not challenge_id or not code:
            return {"error": "challenge_id and code are required"}, 400

        limiter = RateLimitService()
        limiter.enforce(
            scope="mfa:totp:verify:challenge",
            identifier=challenge_id,
            max_attempts=MFA_VERIFY_MAX_ATTEMPTS,
            window_s=MFA_VERIFY_WINDOW_SECONDS,
        )
        limiter.enforce(
            scope="mfa:totp:verify:ip",
            identifier=str(request.remote_addr or "unknown"),
            max_attempts=MFA_VERIFY_MAX_ATTEMPTS * 4,
            window_s=MFA_VERIFY_WINDOW_SECONDS,
        )

        challenge_service = LoginChallengeService()
        user_id = challenge_service.consume_challenge(challenge_id)
        if not user_id:
            logger.info(
                "mfa_event=totp_verify_fail user_id=unknown challenge_id=%s reason=challenge_invalid",
                challenge_id,
            )
            return {"error": "Invalid code or expired challenge"}, 401

        if not TotpService().verify_totp_code(user_id, code):
            logger.info("mfa_event=totp_verify_fail user_id=%s reason=invalid_code", user_id)
            return {"error": "Invalid code or expired challenge"}, 401

        auth = AuthService()
        full_user = None
        try:
            full_user = UserService().get_user(user_id)
        except ForgeError:
            logger.warning("mfa_event=totp_verify user_lookup_failed user_id=%s", user_id)

        token_user = full_user or User(user_id=user_id, user_name=user_id)
        tokens = auth.issue_tokens(token_user)
        workspace_id = _extract_default_workspace_id(full_user or token_user)
        response = make_response(
            {
                "access_token": tokens["access_token"],
                "token_type": "Bearer",
                "expires_in": tokens["expires_in"],
                "mfa_type": "totp",
                "workspace_id": workspace_id,
                "workspaceId": workspace_id,
            },
            200,
        )
        response.set_cookie(
            "refresh_token",
            tokens["refresh_token"],
            httponly=True,
            secure=bool(COOKIE_SECURE),
            samesite=COOKIE_SAMESITE,
            max_age=auth.qf_refresh_ttl,
            path=REFRESH_COOKIE_PATH,
        )
        return response


@qf_auth_ns.route("/mfa/totp/disable")
class DisableTotp(ForgeResource):
    @qf_auth_ns.expect(totp_disable_model, validate=False)
    @token_required
    def post(self):
        user_id = str(getattr(g, "user_id", "") or "").strip()
        data = request.get_json(silent=True) or {}
        password = str(data.get("password") or "")
        code = str(data.get("code") or "")
        if not password or not code:
            return {"error": "password and code are required"}, 400

        RateLimitService().enforce(
            scope="mfa:totp:disable",
            identifier=user_id,
            max_attempts=MFA_DISABLE_MAX_ATTEMPTS,
            window_s=MFA_DISABLE_WINDOW_SECONDS,
        )
        result = TotpService().disable_totp(user_id, password, code)
        return result, 200


def _get_refresh_from_request() -> str | None:
    token = request.cookies.get("refresh_token")
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


@qf_auth_ns.route("/refresh")
class Refresh(ForgeResource):
    def post(self):
        token = _get_refresh_from_request()
        if not token:
            return {"error": "Missing refresh token"}, 401

        auth = AuthService()
        workspace_id = None
        try:
            new_refresh, user_id = auth.rotate_refresh_token(token)
            try:
                full_user = UserService().get_user(user_id)
                workspace_id = _extract_default_workspace_id(full_user)
            except ForgeError:
                logger.warning("refresh user_lookup_failed user_id=%s", user_id)
            access_token = auth.generate_access_token(user_id)
        except ForgeError as e:
            return {"error": str(e)}, getattr(e, "status_code", 401) or 401

        response = make_response(
            jsonify(
                {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_in": auth.access_ttl_seconds,
                    "workspace_id": workspace_id,
                    "workspaceId": workspace_id,
                }
            )
        )
        response.set_cookie(
            "refresh_token",
            new_refresh,
            httponly=True,
            secure=bool(COOKIE_SECURE),
            samesite=COOKIE_SAMESITE,
            max_age=auth.qf_refresh_ttl,
            path=REFRESH_COOKIE_PATH,
        )
        return response


@qf_auth_ns.route("/logout")
class Logout(ForgeResource):
    def post(self):
        auth = AuthService()
        refresh_token = request.cookies.get("refresh_token")
        access_token = None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            access_token = auth_header.split(" ", 1)[1].strip()

        if not refresh_token and not access_token:
            return {"error": "Missing credentials"}, 401

        if refresh_token:
            try:
                payload = auth.decode_and_verify(refresh_token, expected_typ="refresh")
                jti = payload.get("jti")
                if jti:
                    auth.revoke_refresh_jti(jti)
            except ForgeError:
                return {"error": "Invalid refresh token"}, 401

        if access_token:
            if not auth.verify_token(access_token):
                return {"error": "Invalid access token"}, 401

        response = make_response(("", 204))
        response.set_cookie(
            "refresh_token",
            "",
            httponly=True,
            secure=bool(COOKIE_SECURE),
            samesite=COOKIE_SAMESITE,
            max_age=0,
            path=REFRESH_COOKIE_PATH,
        )
        return response

@qf_auth_ns.route("/invite/validate/<string:token>")
class InviteValidationResource(ForgeResource):
    def get(self, token):
        if not token:
            return {"error": "Missing token"}, 400

        try:
            user_id = validate_token(token)
            user_service = UserService()
            user = user_service.get_user(user_id)
            return {"email": user.email, "user_id": user_id}
        except Exception:
            return {"error": "Invalid or expired token"}, 400


@qf_auth_ns.route("/invite/accept")
class InviteAcceptResource(ForgeResource):
    @qf_auth_ns.expect(invite_accept_model, validate=False)
    @qf_auth_ns.doc(security=[])
    def post(self):
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return {"error": "Invalid request body"}, 400

        token = _extract_invite_token(body)
        if not token:
            return {"error": "Missing token"}, 400

        try:
            user_id = str(validate_token(token)).strip()
        except Exception:
            return {"error": "Invalid or expired token"}, 400
        if not user_id:
            return {"error": "Invalid or expired token"}, 400

        password = str(body.get("password") or "").strip()
        if not password:
            return {"error": "password is required"}, 400

        tos_accepted = body.get("tos_accepted")
        if tos_accepted is None:
            tos_accepted = True

        eula_accepted = body.get("eula_accepted")
        if eula_accepted is None:
            eula_accepted = True

        two_factor_preference = str(body.get("two_factor_preference") or "").strip() or "Email"

        user_service = UserService()
        try:
            current_user = user_service.get_user(user_id)
        except ForgeError:
            return {"error": "Invalid or expired token"}, 400

        status_text = str(getattr(current_user, "status", "") or "").strip().lower()
        if status_text not in {str(UserStatus.INVITED).lower(), "invited"}:
            return {"error": "Invite already accepted or inactive"}, 409

        email_in = str(body.get("email") or "").strip()
        invited_email = str(getattr(current_user, "email", "") or "").strip()
        if email_in and invited_email and email_in.lower() != invited_email.lower():
            return {"error": "Email does not match invited account"}, 403

        update_payload = User(
            first_name=str(body.get("first_name") or "").strip() or None,
            last_name=str(body.get("last_name") or "").strip() or None,
            password=password,
            tos_accepted=bool(tos_accepted),
            eula_accepted=bool(eula_accepted),
            two_factor_preference=two_factor_preference,
            status=UserStatus.ACTIVE,
        )

        try:
            updated = user_service.update_user(user_id=user_id, update_data=update_payload)
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

        return {
            "user_id": str(updated.user_id),
            "email": str(updated.email or ""),
            "status": str(updated.status or UserStatus.ACTIVE),
        }, 200

@qf_auth_ns.route("/reset/request")
class ResetPasswordRequest(ForgeResource):
    def post(self):
        email = request.json["email"]
        auth = AuthService()

        return auth.send_reset_request(email)
    
@qf_auth_ns.route("/reset/validate")
class ResetPasswordValidate(ForgeResource):
    def post(self):
        token = request.json["token"]
        
        if not token:
            return {"error": "Missing token"}, 400
        
        auth = AuthService()
        if auth.validate_token(token):
            response = make_response(("", 204))
            response.set_cookie("reset_session", hash_token(token), max_age=900, httponly=True, secure=True, samesite="Strict")
            return response
        else:
            return  {"error": "Missing token"}, 400

@qf_auth_ns.route("/reset/password")
class ResetPassword(ForgeResource):
    def post(self):
        token_hash = request.cookies.get("reset_session")

        if not token_hash:
            return ("", 400)
        
        password = request.json["password"]

        if not password:
            return ("", 400)
        

        auth = AuthService()
        return auth.reset_password(password, token_hash)

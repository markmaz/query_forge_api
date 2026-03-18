from flask import make_response, request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.config import COOKIE_SAMESITE, COOKIE_SECURE, REFRESH_COOKIE_PATH
from app.decorators.rbac import public
from app.services.auth_service import AuthService
from app.services.otp_service import verify_otp_challenge

otp_ns = Namespace("otp", description="A product available in Workboard")

@otp_ns.route("/verify")
class VerifyOTP(ForgeResource):
    @public
    def post(self):
        data = request.get_json(silent=True) or {}
        challenge_id = (data.get("challenge_id") or "").strip()
        otp_raw = data.get("otp")
        otp = str(otp_raw).strip() if otp_raw is not None else ""
        if otp.isdigit() and len(otp) < 6:
            otp = otp.zfill(6)

        if not challenge_id or not otp:
            return {"error": "challenge_id and otp are required"}, 400

        user = verify_otp_challenge(
            challenge_id=challenge_id,
            otp=otp,
            ip_address=request.remote_addr,
        )
        if not user:
            return {"error": "Invalid code or expired challenge"}, 401

        auth = AuthService()
        tokens = auth.issue_tokens(user)
        workspaces = getattr(user, "workspaces", None) or []
        default_ws = next((w for w in workspaces if getattr(w, "is_default", False)), None)
        workspace_id = getattr(default_ws, "workspace_id", None)
        response = make_response(
            {
                "access_token": tokens["access_token"],
                "token_type": "Bearer",
                "expires_in": tokens["expires_in"],
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

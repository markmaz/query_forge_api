from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from app.config import COOKIE_SAMESITE, COOKIE_SECURE, REFRESH_COOKIE_PATH
from app.services.auth_service import AuthService
from app.services.otp_service import generate_otp, verify_otp

otp_ns = Namespace("otp", description="A product available in Workboard")

@otp_ns.route("/generate/<string:user_id>")
class GenerateOTP(Resource):
    def get(self, user_id: str):
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        otp = generate_otp(user_id)
        return jsonify({"otp": otp})

@otp_ns.route("/verify")
class VerifyOTP(Resource):
    def post(self):
        data = request.json
        user_id = data.get("user_id")
        otp_raw = data.get("otp")
        otp = str(otp_raw).strip() if otp_raw is not None else ""
        if otp.isdigit() and len(otp) < 6:
            otp = otp.zfill(6)

        if not user_id or not otp:
            return jsonify({"error": "user_id and otp are required"}), 400

        user = verify_otp(user_id, otp)
        if not user:
            return jsonify({"error": "Invalid OTP"}), 401

        auth = AuthService()
        tokens = auth.issue_tokens(user)
        response = make_response(
            jsonify(
                {
                    "access_token": tokens["access_token"],
                    "token_type": "Bearer",
                    "expires_in": tokens["expires_in"],
                }
            )
        )
        response.set_cookie(
            "refresh_token",
            tokens["refresh_token"],
            httponly=True,
            secure=bool(COOKIE_SECURE),
            samesite=COOKIE_SAMESITE,
            max_age=auth.refresh_ttl_seconds,
            path=REFRESH_COOKIE_PATH,
        )
        return response

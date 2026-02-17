from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from app.config import COOKIE_SAMESITE, COOKIE_SECURE, REFRESH_COOKIE_PATH
from app.exceptions.service_error import ServiceError
from app.services.auth_service import AuthService, hash_token
from app.services.otp_service import OTP_CHALLENGE_TTL_S, issue_otp_challenge
from app.services.user_service import UserService
from app.utils.token_utils import validate_token

auth_ns = Namespace('auth', description='Authentication operations')

login_model = auth_ns.model('Login', {
    'username': fields.String(required=True, description="Username"),
    'password': fields.String(required=True, description="Password")
})

@auth_ns.route('/auth')
@auth_ns.expect(login_model)
class Authenticate(Resource):
    def post(self):
        data = request.json
        username = data.get("username")
        password = data.get("password")

        auth = AuthService()
        user = auth.non_interactive_authentication(username, password)

        if not user:
            return {"message": "Invalid username or password"}, 401

        tokens = auth.issue_tokens(user)
        response = make_response(
            jsonify(
                {
                    "access_token": tokens["access_token"],
                    "token_type": "Bearer",
                    "expires_in": tokens["expires_in"],
                    "token": tokens["access_token"],
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

@auth_ns.route('/login')
@auth_ns.expect(login_model)
class Login(Resource):
    @auth_ns.expect(login_model)
    @auth_ns.response(code=200, description="Credentials accepted and OTP challenge issued")
    @auth_ns.doc(security=[])
    @auth_ns.doc(
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
        data = request.json
        username = data.get("username")
        password = data.get("password")

        auth = AuthService()
        user = auth.authenticate(username, password)
        if not user:
            return {"message": "Invalid username or password"}, 401

        challenge_id = issue_otp_challenge(
            user_id=str(user["user_id"]),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
        return jsonify(
            {
                "requires_otp": True,
                "challenge_id": challenge_id,
                "challenge_expires_in": OTP_CHALLENGE_TTL_S,
            }
        )


def _get_refresh_from_request() -> str | None:
    token = request.cookies.get("refresh_token")
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


@auth_ns.route("/refresh")
class Refresh(Resource):
    def post(self):
        token = _get_refresh_from_request()
        if not token:
            return {"error": "Missing refresh token"}, 401

        auth = AuthService()
        try:
            new_refresh, user_id = auth.rotate_refresh_token(token)
            access_token = auth.generate_access_token(user_id)
        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 401) or 401

        response = make_response(
            jsonify(
                {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_in": auth.access_ttl_seconds,
                }
            )
        )
        response.set_cookie(
            "refresh_token",
            new_refresh,
            httponly=True,
            secure=bool(COOKIE_SECURE),
            samesite=COOKIE_SAMESITE,
            max_age=auth.refresh_ttl_seconds,
            path=REFRESH_COOKIE_PATH,
        )
        return response


@auth_ns.route("/logout")
class Logout(Resource):
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
            except ServiceError:
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

@auth_ns.route("/invite/validate/<string:token>")
class InviteValidationResource(Resource):
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

@auth_ns.route("/reset/request")
class ResetPasswordRequest(Resource):
    def post(self):
        email = request.json["email"]
        auth = AuthService()

        return auth.send_reset_request(email)
    
@auth_ns.route("/reset/validate")
class ResetPasswordValidate(Resource):
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

@auth_ns.route("/reset/password")
class ResetPassword(Resource):
    def post(self):
        token_hash = request.cookies.get("reset_session")

        if not token_hash:
            return ("", 400)
        
        password = request.json["password"]

        if not password:
            return ("", 400)
        

        auth = AuthService()
        return auth.reset_password(password, token_hash)

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from app.services.auth_service import AuthService, hash_token
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
        else:
            token = auth.generate_token(user)
            return {"token": token}

@auth_ns.route('/login')
@auth_ns.expect(login_model)
class Login(Resource):
    @auth_ns.expect(login_model)
    @auth_ns.response(code=200, description="Successful authentication")
    @auth_ns.doc(security=[])
    @auth_ns.doc(
        description=(
            "## Authentication\n"
            "This endpoint allows a user to authenticate inside the application and obtain a JWT Token. The user can then take this token and pass it in the header `Authentication` with `Bearer` and the token\n\n"
            "**Required URL Parameters:**\n"
            "- `username`: The username for the application.\n"
            "- `password`: The password for the application\n\n"
            "**Response Codes:**\n"
            "- `200`: Authenticated successfully and a token returned (See model).\n"
            "- `401`: Invalid username or password"
        )
    )
    def post(self):
        """JWT Authentication"""
        data = request.json
        username = data.get("username")
        password = data.get("password")

        auth = AuthService()
        user = auth.authenticate(username, password)
        print(user)
        if not user:
            return {"message": "Invalid username or password"}, 401

        return jsonify(user)

@auth_ns.route("/invite/validate/<string:token>")
class InviteValidationResource(Resource):
    def get(self, token):
        if not token:
            return {"error": "Missing token"}, 400

        try:
            user_id = validate_token(token)
            user_service = UserService()

            user = user_service.get_user(user_id)
            if not user:
                return {"error": "Invalid or expired token"}, 404

            return {"email": user.email, "user_id": user_id}
        except Exception as e:
            return {"error": str(e)}, 400

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



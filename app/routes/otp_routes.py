from flask import jsonify, request
from flask_restx import Namespace, Resource

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
        otp = data.get("otp")

        if not user_id or not otp:
            return jsonify({"error": "user_id and otp are required"}), 400

        token = verify_otp(user_id, otp)
        return jsonify({"token": token})

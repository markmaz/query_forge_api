from flask_restx import Namespace, Resource

from app.config import DB_URI
from app.decorators.security import token_required
from app.services.base_token_manager import DATABRICKS_TOKEN, SIGMA_TOKEN, get_headers

admin_ns = Namespace("admin", description="Admin operations")

@admin_ns.route("/headers/<string:token_manager>")
class GetHeaders(Resource):
    @token_required
    def get(self, token_manager):
        if token_manager in (DATABRICKS_TOKEN, SIGMA_TOKEN):
            return get_headers(token_manager)
        else:
            return 400

@admin_ns.route("/")
class ShowEnv(Resource):
    def get(self):
        return {"DB_URI": DB_URI}, 200

@admin_ns.route("/healthz")
class ShowHealth(Resource):
    def get(self):
        return "OK", 200
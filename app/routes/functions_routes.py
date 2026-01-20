from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.services.udf_service import UdfService

functions_ns = Namespace("functions", description="miscellaneous functions")


@functions_ns.route("/diagnosis_code_details/<string:diag_details>")
@functions_ns.response(200, "The results of the query")
class GetDiagDetails(Resource):
    @token_required
    def get(self, diag_details):
        udf = UdfService()

        return udf.get_diag_code_details(diag_details)
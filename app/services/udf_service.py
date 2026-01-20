import json

import requests

from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import DATABRICKS_TOKEN, get_headers


class UdfService:

    @validate_params("diag_code")
    def get_diag_code_details(self, diag_code: str):
        host = "https://wayfinder-kythera-dev.cloud.databricks.com/"
        sql = f"SELECT kythera_research.default.diagdetails('{diag_code}')"
        data = {"statement": sql, "warehouse_id": "94482e09c87938af"}

        try:
            response = requests.post(
                build_url(host, "api", "2.0", "sql", "statements"),
                headers=get_headers(DATABRICKS_TOKEN),
                json=data,
                timeout=5,
            )
            details = process_response(response)["result"]
            data_array = details["data_array"][0][0]
            if data_array is None:
                raise ServiceError("Diagnosis details not found", status_code=404)
            return json.loads(data_array)
        except ServiceError as e:
            status = getattr(e, "status_code", 500) or 500
            if status >= 500:
                raise ServiceError("Upstream error", status_code=424)
            raise
        except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError, TypeError, ValueError):
            raise ServiceError("Upstream error", status_code=424)

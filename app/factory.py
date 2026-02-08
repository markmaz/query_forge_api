from __future__ import annotations

import json
import logging
import time
import uuid

import valkey
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from flask_restx import Api

from app.adapters.databricks_token_manager import DatabricksTokenManager
from app.adapters.sigma_token_manager import SigmaTokenManager
from app.celery_app import celery, init_celery
from app.config import LOG_QUEUE, VALKEY_ADDRESS, VALKEY_CONFIG, VALKEY_PORT
from app.config.logging_config import configure_logging
from app.config.mail_config import MailConfig
from app.exceptions.service_error import ServiceError
from app.extensions import mail
from app.routes.admin_routes import admin_ns
from app.routes.auth_routes import auth_ns
from app.routes.connection_routes import connection_ns
from app.routes.crosswalk_routes import crosswalk_ns
from app.routes.dashboard_routes import dashboard_ns
from app.routes.domain_routes import domains_ns
from app.routes.embeddings import embeddings_ns
from app.routes.execution_routes import executions_ns
from app.routes.export_routes import exports_ns
from app.routes.functions_routes import functions_ns
from app.routes.model_routes import model_ns
from app.routes.nlp_routes import nlp_ns
from app.routes.no_code_query_routes import nocode_ns
from app.routes.otp_routes import otp_ns
from app.routes.product_groups_routes import product_group_ns
from app.routes.product_routes import product_ns
from app.routes.public_sales_inquiry import public_ns
from app.routes.query_tree_routes import saved_query_ns, tree_ns
from app.routes.role_routes import role_ns
from app.routes.user_routes import user_ns
from app.routes.user_workspace_routes import user_workspace_ns
from app.routes.workspace_inventory_routes import wsinv_ns
from app.routes.workspace_routes import workspace_ns
from app.routes.workspace_table_routes import workspace_tables_ns
from app.services.auth_service import AuthService
from app.services.base_service import build_url

NAME = "api"
VERSION = "v1"

auth_service = AuthService()

def try_get_json_body(req):
    try:
        data = req.get_json()
        if data:
            masked = data.copy()
            for key in ["password", "token"]:
                if key in masked:
                    masked[key] = "*****"
            return masked
    except Exception:
        pass
    return None

def extract_user_id():
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        payload = auth_service.verify_token(token)
        if payload and isinstance(payload, dict):
            return payload.get("sub") or "unknown_user"
        return "unknown_user"
    return "unknown_user"

def create_app():
    app = Flask(__name__)
    app.config["RESTX_MASK_SWAGGER"] = False
    app.url_map.strict_slashes = False
    authorizations = {"BearerAuth": {"type": "apiKey", "in": "header", "name": "Authorization"}}

    app.config.from_object(MailConfig)
    mail.init_app(app=app)

    app.config["CELERY_BROKER_URL"] = VALKEY_CONFIG
    app.config["CELERY_RESULT_BACKEND"] = VALKEY_CONFIG

    init_celery(app)
    app.config["CELERY"] = celery

    api = Api(
        app,
        version="1.0",
        title="Wayfinder API",
        description="The Wayfinder API",
        doc="/swagger-ui",
        mask_swagger=False,
        security="BearerAuth",
        authorizations=authorizations,
    )

    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=True,
        expose_headers=["Content-Disposition"],
    )

    api.add_namespace(auth_ns, path=build_url("/", NAME, VERSION, "auth"))
    api.add_namespace(user_ns, path=build_url("/", NAME, VERSION, "users"))
    api.add_namespace(workspace_ns, path=build_url("/", NAME, VERSION, "workspaces"))
    api.add_namespace(workspace_tables_ns, path=build_url("/", NAME, VERSION, "workspace-tables"))
    api.add_namespace(dashboard_ns, path=build_url("/", NAME, VERSION, "dashboards"))
    api.add_namespace(connection_ns, path=build_url("/", NAME, VERSION, "connections"))
    api.add_namespace(user_workspace_ns, path=build_url("/", NAME, VERSION, "user-workspaces"))
    api.add_namespace(role_ns, path=build_url("/", NAME, VERSION, "roles"))
    api.add_namespace(functions_ns, path=build_url("/", NAME, VERSION, "functions"))
    api.add_namespace(admin_ns, path=build_url("/", NAME, VERSION, "admin"))
    api.add_namespace(product_ns, path=build_url("/", NAME, VERSION, "products"))
    api.add_namespace(otp_ns, path=build_url("/", NAME, VERSION, "otp"))
    api.add_namespace(product_group_ns, path=build_url("/", NAME, VERSION, "product-groups"))
    api.add_namespace(crosswalk_ns, path=build_url("/", NAME, VERSION, "crosswalks"))
    api.add_namespace(public_ns, path=build_url("/", NAME, VERSION, "public"))
    api.add_namespace(domains_ns, path=build_url("/", NAME, VERSION, "domains"))
    api.add_namespace(embeddings_ns, path=build_url("/", NAME, VERSION, "embeddings"))
    api.add_namespace(executions_ns, path=build_url("/", NAME, VERSION, "executions"))
    api.add_namespace(exports_ns, path=build_url("/", NAME, VERSION, "exports"))
    api.add_namespace(wsinv_ns, path=build_url("/", NAME, VERSION, "workspace-inventory"))
    api.add_namespace(model_ns, path=build_url("/", NAME, VERSION, "models"))
    api.add_namespace(nlp_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nocode_ns, path=build_url("/", NAME, VERSION, "query"))
    api.add_namespace(tree_ns, path=build_url("/", NAME, VERSION, "query-tree"))
    api.add_namespace(saved_query_ns, path=build_url("/", NAME, VERSION, "saved-queries"))

    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting the application...")

    databricks_token_manager = DatabricksTokenManager()
    sigma_token_manager = SigmaTokenManager()
    databricks_token_manager.start_auto_refresh()
    sigma_token_manager.start_auto_refresh()

    app.config["DATABRICKS_TOKEN_MANAGER"] = databricks_token_manager
    app.config["SIGMA_TOKEN_MANAGER"] = sigma_token_manager

    valkey_client = valkey.StrictValkey(host=VALKEY_ADDRESS, port=VALKEY_PORT, decode_responses=True)

    @app.before_request
    def log_request_metadata():
        g.start_time = time.time()
        g.correlation_id = str(uuid.uuid4())
        g.audit_data = {
            "timestamp": int(g.start_time),
            "correlation_id": g.correlation_id,
            "user_id": extract_user_id(),
            "endpoint": request.path,
            "method": request.method,
            "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr),
            "user_agent": request.headers.get("User-Agent", "unknown"),
            "request_body": try_get_json_body(request),
            "authenticated": request.authorization is not None or hasattr(g, "user"),
        }

    @app.after_request
    def log_response_metadata(response):
        duration_ms = int((time.time() - g.start_time) * 1000)
        g.audit_data["status_code"] = response.status_code
        g.audit_data["response_time_ms"] = duration_ms
        try:
            valkey_client.rpush(LOG_QUEUE, json.dumps(g.audit_data))
        except Exception as e:
            app.logger.error(f"Error storing audit log in Valkey: {e}")

        response.headers["X-Correlation-ID"] = g.correlation_id
        return response

    @app.errorhandler(ServiceError)
    def handle_service_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response

    return app

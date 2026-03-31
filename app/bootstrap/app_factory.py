from __future__ import annotations

import valkey
from flask import Flask

from app.config import VALKEY_ADDRESS, VALKEY_PORT
from app.services.auth_service import AuthService

from .error_handlers import register_error_handlers
from .extensions import (
    apply_runtime_config,
    init_framework_extensions,
    initialize_domain_extensions,
    initialize_startup_tasks,
    register_cli_commands,
)
from .middleware import extract_user_id, register_request_middleware, register_teardown_handlers, try_get_json_body

auth_service = AuthService()
__all__ = ["auth_service", "create_app", "extract_user_id", "try_get_json_body"]


def create_app():
    app = Flask(__name__)
    apply_runtime_config(app)
    init_framework_extensions(app)
    initialize_startup_tasks()
    audit_client = valkey.StrictValkey(host=VALKEY_ADDRESS, port=VALKEY_PORT, decode_responses=True)
    register_request_middleware(app, auth_service=auth_service, audit_client=audit_client)
    register_teardown_handlers(app)
    register_error_handlers(app)
    initialize_domain_extensions(app)
    register_cli_commands(app)
    return app

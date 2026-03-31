from __future__ import annotations

import json
import time
import uuid
from typing import Optional

import valkey
from flask import Flask, g, request

from app.config import LOG_QUEUE
from app.extensions import db


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


def extract_user_id(request_obj, *, auth_service):
    auth_header = request_obj.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        payload = auth_service.verify_token(token)
        if payload and isinstance(payload, dict):
            return payload.get("sub") or "unknown_user"
        return "unknown_user"
    return "unknown_user"


def register_request_middleware(app: Flask, *, auth_service, audit_client: valkey.StrictValkey) -> None:
    @app.before_request
    def log_request_metadata():
        g.start_time = time.time()
        g.correlation_id = str(uuid.uuid4())
        g.audit_data = {
            "timestamp": int(g.start_time),
            "correlation_id": g.correlation_id,
            "user_id": extract_user_id(request, auth_service=auth_service),
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
            audit_client.rpush(LOG_QUEUE, json.dumps(g.audit_data))
        except Exception as error:
            app.logger.error(f"Error storing audit log in Valkey: {error}")

        response.headers["X-Correlation-ID"] = g.correlation_id
        return response


def register_teardown_handlers(app: Flask) -> None:
    @app.teardown_appcontext
    def cleanup_db_session(exception: Optional[BaseException]) -> None:
        del exception
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            db.session.remove()
        except Exception:
            pass

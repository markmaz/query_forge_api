import valkey

from app.bootstrap import app_factory as _app_factory
from app.bootstrap import extensions as _extensions
from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    AWS_SESSION_TOKEN,
    LLM_INSTANCE_ID,
    LLM_STATUS_CACHE_SECONDS,
)

auth_service = _app_factory.auth_service
extract_user_id = _app_factory.extract_user_id
try_get_json_body = _app_factory.try_get_json_body


def create_app():
    _app_factory.valkey = valkey
    _app_factory.auth_service = auth_service
    _extensions.AWS_REGION = AWS_REGION
    _extensions.AWS_ACCESS_KEY_ID = AWS_ACCESS_KEY_ID
    _extensions.AWS_SECRET_ACCESS_KEY = AWS_SECRET_ACCESS_KEY
    _extensions.AWS_SESSION_TOKEN = AWS_SESSION_TOKEN
    _extensions.LLM_INSTANCE_ID = LLM_INSTANCE_ID
    _extensions.LLM_STATUS_CACHE_SECONDS = LLM_STATUS_CACHE_SECONDS
    return _app_factory.create_app()


__all__ = [
    "auth_service",
    "create_app",
    "extract_user_id",
    "try_get_json_body",
    "valkey",
    "LLM_INSTANCE_ID",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "LLM_STATUS_CACHE_SECONDS",
]

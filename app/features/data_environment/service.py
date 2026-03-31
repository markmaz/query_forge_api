from __future__ import annotations

from typing import Optional, Tuple

from flask import current_app

from app.exceptions.forge_error import ForgeError
from app.services.llm_environment_service import LLMEnvironmentService

_service_cache: Optional[LLMEnvironmentService] = None
_service_cache_key: Optional[Tuple[str, str, int, str, str, str]] = None


class DataEnvironmentFeatureService:
    def get_service(self) -> LLMEnvironmentService:
        global _service_cache, _service_cache_key

        region = str(current_app.config.get("AWS_REGION") or "").strip() or "us-east-1"
        instance_id = str(current_app.config.get("LLM_INSTANCE_ID") or "").strip()
        cache_seconds = int(current_app.config.get("LLM_STATUS_CACHE_SECONDS") or 5)
        aws_access_key_id = str(current_app.config.get("AWS_ACCESS_KEY_ID") or "").strip()
        aws_secret_access_key = str(current_app.config.get("AWS_SECRET_ACCESS_KEY") or "").strip()
        aws_session_token = str(current_app.config.get("AWS_SESSION_TOKEN") or "").strip()

        cache_key = (
            region,
            instance_id,
            cache_seconds,
            aws_access_key_id,
            aws_secret_access_key,
            aws_session_token,
        )
        if _service_cache is None or _service_cache_key != cache_key:
            _service_cache = LLMEnvironmentService(
                region=region,
                instance_id=instance_id,
                cache_seconds=cache_seconds,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token or None,
            )
            _service_cache_key = cache_key
        return _service_cache

    @staticmethod
    def handle_service_error(error: ForgeError):
        return {"error": str(error), "details": error.details}, error.status_code


data_environment_feature_service = DataEnvironmentFeatureService()

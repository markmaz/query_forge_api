# app/services/ai_suggest/vllm_client.py
from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from app.services.llm.io_logging import (
    log_llm_exception,
    log_llm_request,
    log_llm_response,
    new_llm_request_id,
)

logger = logging.getLogger(__name__)


class VllmClient:
    """HTTP transport for the vLLM chat completion endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: int,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

    def call(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        request_id = new_llm_request_id()
        log_llm_request(
            logger,
            client_name="AISuggestService.chat",
            request_id=request_id,
            method="POST",
            url=url,
            payload=payload,
        )
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            log_llm_exception(
                logger,
                client_name="AISuggestService.chat",
                request_id=request_id,
                method="POST",
                url=url,
                message=str(exc),
            )
            raise
        log_llm_response(
            logger,
            client_name="AISuggestService.chat",
            request_id=request_id,
            status_code=response.status_code,
            response_text=getattr(response, "text", ""),
        )
        response.raise_for_status()
        return response.json()

    def extract_content(self, response_json: Dict[str, Any]) -> str:
        from app.services.ai_suggest.service import InvalidModelResponseError

        try:
            content = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("AI suggest response missing expected content path: %s", response_json)
            raise InvalidModelResponseError(
                {
                    "type": "invalid_response_shape",
                    "message": str(exc),
                }
            ) from exc

        if not isinstance(content, str):
            raise InvalidModelResponseError(
                {
                    "type": "invalid_content_type",
                    "message": f"Expected string content, got {type(content).__name__}",
                }
            )
        return content

    def health(self) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/models"
        request_id = new_llm_request_id()
        log_llm_request(
            logger,
            client_name="AISuggestService.health",
            request_id=request_id,
            method="GET",
            url=url,
            payload=None,
        )
        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            log_llm_exception(
                logger,
                client_name="AISuggestService.health",
                request_id=request_id,
                method="GET",
                url=url,
                message=str(exc),
            )
            raise
        log_llm_response(
            logger,
            client_name="AISuggestService.health",
            request_id=request_id,
            status_code=response.status_code,
            response_text=response.text,
        )
        response.raise_for_status()
        return response.json()

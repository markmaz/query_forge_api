from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional
from uuid import uuid4


def new_llm_request_id() -> str:
    return uuid4().hex[:12]


def log_llm_request(
    logger: logging.Logger,
    *,
    client_name: str,
    request_id: str,
    method: str,
    url: str,
    payload: Optional[Mapping[str, Any]],
) -> None:
    logger.info(
        "llm_io client=%s request_id=%s direction=request method=%s url=%s payload=%s",
        client_name,
        request_id,
        method.upper(),
        url,
        _to_log_text(payload),
    )


def log_llm_response(
    logger: logging.Logger,
    *,
    client_name: str,
    request_id: str,
    status_code: int,
    response_text: str,
) -> None:
    logger.info(
        "llm_io client=%s request_id=%s direction=response status_code=%s body=%s",
        client_name,
        request_id,
        int(status_code),
        _to_log_text(response_text),
    )


def log_llm_exception(
    logger: logging.Logger,
    *,
    client_name: str,
    request_id: str,
    method: str,
    url: str,
    message: str,
) -> None:
    logger.exception(
        "llm_io client=%s request_id=%s direction=error method=%s url=%s message=%s",
        client_name,
        request_id,
        method.upper(),
        url,
        message,
    )


def _to_log_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True, default=str, separators=(",", ":"))
    except Exception:
        return str(value)

from __future__ import annotations

import logging
from typing import Any

from requests import Response

from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)

_SUCCESS_CODES = {200, 201}


def process_response(response: Response) -> dict[str, Any] | list[Any]:
    """Return decoded JSON for successful responses or raise ForgeError."""
    if int(response.status_code) in _SUCCESS_CODES:
        return response.json()

    payload = _safe_json(response)
    logger.error("API error status=%s body=%s", response.status_code, response.text)
    raise ForgeError(payload, status_code=int(response.status_code))


def build_url(*parts: str) -> str:
    """Join URL/path fragments with exactly one slash separator."""
    if not parts:
        return ""

    normalized = [str(parts[0]).rstrip("/")]
    normalized.extend(str(part).strip("/") for part in parts[1:])
    url = "/".join(normalized)
    logger.debug("Built URL: %s", url)
    return url


def _safe_json(response: Response) -> dict[str, Any]:
    try:
        decoded = response.json()
        if isinstance(decoded, dict):
            return decoded
        return {"error": decoded}
    except Exception:
        return {"error": response.text or "Unknown API error"}

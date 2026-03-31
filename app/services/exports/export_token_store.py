from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Optional


class ExportTokenStore:
    def __init__(self, *, client_factory: Callable[[], Any], ttl_seconds: int = 300) -> None:
        self._client_factory = client_factory
        self._ttl_seconds = ttl_seconds

    def set_export_job(self, payload: dict[str, Any]) -> str:
        token = uuid.uuid4().hex
        key = f"qf:export:{token}"
        data = json.dumps(payload, default=str)
        self._client_factory().setex(key, self._ttl_seconds, data)
        return token

    def pop_export_job(self, token: str) -> Optional[dict[str, Any]]:
        key = f"qf:export:{token}"
        client = self._client_factory()
        data = client.get(key)
        if not data:
            return None
        client.delete(key)
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

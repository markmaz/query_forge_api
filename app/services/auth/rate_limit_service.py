from __future__ import annotations

import logging
from typing import Any

import redis

from app.config import VALKEY_CONFIG
from app.exceptions.service_error import ServiceError

logger = logging.getLogger(__name__)


class RateLimitService:
    def __init__(self, *, redis_client: Any | None = None) -> None:
        self._redis = redis_client or redis.Redis.from_url(VALKEY_CONFIG, decode_responses=True)

    def increment(self, *, scope: str, identifier: str, window_s: int) -> tuple[int, int]:
        key = self._rate_key(scope=scope, identifier=identifier)
        count = int(self._redis.incr(key))
        if count == 1:
            self._redis.expire(key, int(window_s))
        ttl = int(self._redis.ttl(key) or 0)
        return count, max(ttl, 0)

    def enforce(
        self,
        *,
        scope: str,
        identifier: str,
        max_attempts: int,
        window_s: int,
        message: str = "Too many attempts. Please try again later.",
    ) -> None:
        if max_attempts <= 0:
            return
        key_id = str(identifier or "unknown").strip() or "unknown"
        try:
            count, ttl = self.increment(scope=scope, identifier=key_id, window_s=window_s)
        except Exception:
            # Fail-open if Valkey is unavailable so auth does not hard fail.
            logger.warning("rate_limit_unavailable scope=%s identifier=%s", scope, key_id, exc_info=True)
            return

        if count > max_attempts:
            raise ServiceError(message, status_code=429, details={"retry_after_seconds": ttl})

    @staticmethod
    def _rate_key(*, scope: str, identifier: str) -> str:
        return f"rate:{scope}:{identifier}"

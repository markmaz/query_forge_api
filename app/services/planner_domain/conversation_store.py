from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Protocol

from app.config import QF_PLAN_DOMAIN_CONVERSATION_TTL_SECONDS, VALKEY_ADDRESS, VALKEY_PORT

logger = logging.getLogger(__name__)

_IN_MEMORY_CONV_STORE: Dict[str, str] = {}
_valkey_client: Any = None

try:
    import valkey  # type: ignore
    from valkey.exceptions import ValkeyError
except ImportError:  # pragma: no cover
    valkey = None
    ValkeyError = None  # type: ignore[assignment]


VALKEY_BACKEND_ERRORS = ((OSError, ValkeyError) if ValkeyError is not None else (OSError,))
JSON_PARSE_ERRORS = (TypeError, ValueError)


class PlannerDomainConversationStore(Protocol):
    def get_state(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        ...

    def save_state(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        state: Mapping[str, Any],
        qf_ttl_seconds: int,
    ) -> None:
        ...


class HybridPlannerDomainConversationStore:
    def get_state(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        key = _conversation_store_key(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id)
        payload = self._read(key)
        if payload is None:
            return None
        try:
            data = json.loads(payload)
        except JSON_PARSE_ERRORS:
            logger.debug("planner_domain conversation payload parse failed key=%s", key)
            return None
        if not isinstance(data, Mapping):
            return None
        return dict(data)

    def save_state(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        state: Mapping[str, Any],
        qf_ttl_seconds: int,
    ) -> None:
        key = _conversation_store_key(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id)
        payload = json.dumps(dict(state), ensure_ascii=True, separators=(",", ":"))
        self._write(key, payload, qf_ttl_seconds)

    def _read(self, key: str) -> Optional[str]:
        client = _get_valkey_client()
        if client is not None:
            try:
                value = client.get(key)
                if isinstance(value, bytes):
                    return value.decode("utf-8", errors="ignore")
                if isinstance(value, str):
                    return value
            except VALKEY_BACKEND_ERRORS:
                logger.debug("planner_domain valkey read failed", exc_info=True)
        return _IN_MEMORY_CONV_STORE.get(key)

    def _write(self, key: str, value: str, qf_ttl_seconds: int) -> None:
        client = _get_valkey_client()
        if client is not None:
            try:
                client.setex(key, int(qf_ttl_seconds), value)
                return
            except VALKEY_BACKEND_ERRORS:
                logger.debug("planner_domain valkey write failed", exc_info=True)
        _IN_MEMORY_CONV_STORE[key] = value


def new_conversation_id() -> str:
    return f"pdc_{uuid.uuid4().hex[:20]}"


def default_conversation_ttl_seconds() -> int:
    return max(60, int(QF_PLAN_DOMAIN_CONVERSATION_TTL_SECONDS or 43200))


def build_conversation_state(
    *,
    workspace_id: str,
    user_id: str,
    prompt: str,
    trace_id: str,
    plan_json_v2: Mapping[str, Any],
    sql_json: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "last_prompt": str(prompt or "").strip(),
        "trace_id": str(trace_id or "").strip(),
        "plan_json_v2": dict(plan_json_v2 or {}),
        "sql_json": dict(sql_json or {}),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _conversation_store_key(*, workspace_id: str, user_id: str, conversation_id: str) -> str:
    return f"planner:domain:{workspace_id}:{user_id}:{conversation_id}"


def _get_valkey_client():
    global _valkey_client
    if _valkey_client is not None:
        return _valkey_client
    if valkey is None:
        return None
    host = str(VALKEY_ADDRESS or "").strip()
    port = int(VALKEY_PORT or 6379)
    if host == "":
        return None
    try:
        _valkey_client = valkey.Redis(host=host, port=port, decode_responses=False)
        return _valkey_client
    except VALKEY_BACKEND_ERRORS:
        logger.debug("planner_domain valkey init failed", exc_info=True)
        _valkey_client = None
        return None


__all__ = [
    "PlannerDomainConversationStore",
    "HybridPlannerDomainConversationStore",
    "new_conversation_id",
    "default_conversation_ttl_seconds",
    "build_conversation_state",
]

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Protocol, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import (
    QF_MINIMAL_CHAT_CONVERSATION_TTL_SECONDS,
    VALKEY_ADDRESS,
    VALKEY_PORT,
    VLLM_BASE_URL,
    VLLM_MODEL,
    VLLM_TIMEOUT,
)
from app.exceptions.service_error import ServiceError
from app.services.llm.io_logging import (
    log_llm_exception,
    log_llm_request,
    log_llm_response,
    new_llm_request_id,
)

logger = logging.getLogger(__name__)

_MAX_MESSAGES = 30
_MAX_CONTENT_LEN = 8000
_RAW_PREVIEW_LEN = 2000
_ALLOWED_ROLES = {"user", "assistant", "system"}
_MAX_HISTORY_MESSAGES = 80
_IN_MEMORY_CONV_STORE: Dict[str, str] = {}
_valkey_client: Any = None

try:
    import valkey  # type: ignore
except Exception:  # pragma: no cover
    valkey = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        role = str(value or "").strip().lower()
        if role not in _ALLOWED_ROLES:
            raise ValueError("role must be one of user|assistant|system")
        return role

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        text = str(value or "")
        if text.strip() == "":
            raise ValueError("content is required")
        if len(text) > _MAX_CONTENT_LEN:
            raise ValueError(f"content exceeds max length {_MAX_CONTENT_LEN}")
        return text


class MinimalChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: List[ChatMessage]
    conversation_id: Optional[str] = None
    stream: bool = False
    temperature: float = 0.2
    max_tokens: int = 512
    debug: bool = False

    @field_validator("max_tokens")
    @classmethod
    def _validate_max_tokens(cls, value: int) -> int:
        try:
            parsed = int(value)
        except Exception as exc:
            raise ValueError("max_tokens must be an integer") from exc
        if parsed <= 0:
            raise ValueError("max_tokens must be > 0")
        return parsed

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, value: float) -> float:
        try:
            parsed = float(value)
        except Exception as exc:
            raise ValueError("temperature must be numeric") from exc
        if parsed < 0 or parsed > 2:
            raise ValueError("temperature must be between 0 and 2")
        return parsed

    @model_validator(mode="after")
    def _validate_messages_and_stream(self) -> "MinimalChatRequest":
        if not self.messages:
            raise ValueError("messages is required")
        if len(self.messages) > _MAX_MESSAGES:
            raise ValueError(f"messages exceeds max count {_MAX_MESSAGES}")
        if self.stream:
            raise ValueError("stream=true is not supported")
        return self

    @field_validator("conversation_id")
    @classmethod
    def _validate_conversation_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        if token == "":
            return None
        if len(token) > 128:
            raise ValueError("conversation_id too long")
        return token


class ConversationStore(Protocol):
    def get_messages(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Optional[List[Dict[str, str]]]:
        ...

    def save_messages(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        messages: Sequence[Mapping[str, Any]],
        ttl_seconds: int,
    ) -> None:
        ...


class HybridConversationStore:
    def get_messages(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Optional[List[Dict[str, str]]]:
        key = _conversation_store_key(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id)
        payload = self._read(key)
        if payload is None:
            return None
        try:
            data = json.loads(payload)
        except Exception:
            logger.debug("minimal chat conversation payload parse failed key=%s", key)
            return None
        if not isinstance(data, list):
            return None
        out: List[Dict[str, str]] = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "")
            if role in _ALLOWED_ROLES and content.strip() != "":
                out.append({"role": role, "content": content})
        return out

    def save_messages(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        messages: Sequence[Mapping[str, Any]],
        ttl_seconds: int,
    ) -> None:
        key = _conversation_store_key(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id)
        payload = json.dumps(
            [
                {
                    "role": str(m.get("role") or "").strip().lower(),
                    "content": str(m.get("content") or ""),
                }
                for m in messages
                if isinstance(m, Mapping)
            ]
        )
        self._write(key, payload, ttl_seconds)

    def _read(self, key: str) -> Optional[str]:
        client = _get_valkey_client()
        if client is not None:
            try:
                value = client.get(key)
                if isinstance(value, bytes):
                    return value.decode("utf-8", errors="ignore")
                if isinstance(value, str):
                    return value
            except Exception:
                logger.debug("minimal chat valkey read failed", exc_info=True)
        return _IN_MEMORY_CONV_STORE.get(key)

    def _write(self, key: str, value: str, ttl_seconds: int) -> None:
        client = _get_valkey_client()
        if client is not None:
            try:
                client.setex(key, int(ttl_seconds), value)
                return
            except Exception:
                logger.debug("minimal chat valkey write failed", exc_info=True)
        _IN_MEMORY_CONV_STORE[key] = value


class MinimalChatService:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        conversation_store: Optional[ConversationStore] = None,
        conversation_ttl_seconds: Optional[int] = None,
    ) -> None:
        self._base_url = str(base_url or VLLM_BASE_URL or "").strip()
        self._model = str(model or VLLM_MODEL or "").strip() or "qwen"
        self._timeout_seconds = int(timeout_seconds or VLLM_TIMEOUT or 60)
        self._conversation_store = conversation_store or HybridConversationStore()
        self._conversation_ttl_seconds = max(
            60,
            int(conversation_ttl_seconds or QF_MINIMAL_CHAT_CONVERSATION_TTL_SECONDS or 43200),
        )

    def chat(self, body: Mapping[str, Any], *, workspace_id: str, user_id: str) -> Dict[str, Any]:
        try:
            req = MinimalChatRequest.model_validate(dict(body or {}))
        except ValidationError as exc:
            raise ServiceError(
                "Invalid chat request",
                status_code=400,
                details={"errors": _safe_validation_errors(exc)},
            ) from exc
        except ValueError as exc:
            raise ServiceError("Invalid chat request", status_code=400, details={"message": str(exc)}) from exc

        conversation_id = req.conversation_id or _new_conversation_id()
        prior_history = self._conversation_store.get_messages(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if req.conversation_id and prior_history is None:
            raise ServiceError("Conversation not found", status_code=404, details={"conversation_id": conversation_id})
        history = list(prior_history or [])
        new_messages = [m.model_dump(mode="json") for m in req.messages]
        provider_messages = _trim_messages_for_context(history + new_messages)

        provider_payload = {
            "model": self._model,
            "messages": provider_messages,
            "stream": False,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        trace = self._call_provider(provider_payload)
        assistant_content = _extract_assistant_content(trace["body"])
        if assistant_content is None:
            raise ServiceError(
                "Malformed provider response",
                status_code=502,
                details={"message": "missing assistant message content"},
            )

        body = trace["body"]
        usage = _normalize_usage(body.get("usage"))
        finish_reason = _extract_finish_reason(body)
        provider_model = str(body.get("model") or self._model).strip() or self._model

        response: Dict[str, Any] = {
            "id": str(body.get("id") or f"chatcmpl_local_{uuid.uuid4().hex[:12]}"),
            "model": provider_model,
            "created_at": _utc_now_iso(),
            "conversation_id": conversation_id,
            "message": {"role": "assistant", "content": assistant_content},
            "usage": usage,
            "debug": None,
        }
        updated_history = _trim_messages_for_context(
            history + new_messages + [{"role": "assistant", "content": assistant_content}],
            max_messages=_MAX_HISTORY_MESSAGES,
        )
        self._conversation_store.save_messages(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            messages=updated_history,
            ttl_seconds=self._conversation_ttl_seconds,
        )
        if req.debug:
            response["debug"] = {
                "provider_model": provider_model,
                "finish_reason": finish_reason,
                "request_preview": _truncate_preview(provider_payload),
                "response_preview": _truncate_preview(trace.get("raw_text")),
                "status_code": trace.get("status_code"),
                "conversation_history_count": len(updated_history),
            }
        return response

    def _call_provider(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        chat_url = self._chat_url()
        request_id = new_llm_request_id()
        log_llm_request(
            logger,
            client_name="MinimalChatService",
            request_id=request_id,
            method="POST",
            url=chat_url,
            payload=dict(payload),
        )
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(chat_url, json=dict(payload))
        except Exception as exc:
            log_llm_exception(
                logger,
                client_name="MinimalChatService",
                request_id=request_id,
                method="POST",
                url=chat_url,
                message=str(exc),
            )
            raise ServiceError("Chat provider request failed", status_code=502, details={"message": str(exc)}) from exc

        raw_text = resp.text
        log_llm_response(
            logger,
            client_name="MinimalChatService",
            request_id=request_id,
            status_code=resp.status_code,
            response_text=raw_text,
        )
        if resp.status_code >= 400:
            logger.warning("minimal chat provider http_error status=%s", resp.status_code)
            raise ServiceError(
                "Chat provider request failed",
                status_code=502,
                details={
                    "provider_status": resp.status_code,
                    "provider_response": _truncate_preview(raw_text),
                },
            )

        try:
            body = resp.json()
        except Exception as exc:
            raise ServiceError(
                "Malformed provider response",
                status_code=502,
                details={"message": f"response_json_parse_error:{str(exc)}"},
            ) from exc
        if not isinstance(body, dict):
            raise ServiceError("Malformed provider response", status_code=502, details={"message": "response must be object"})
        return {"status_code": resp.status_code, "body": body, "raw_text": raw_text}

    def _chat_url(self) -> str:
        if self._base_url.endswith("/v1/chat/completions"):
            return self._base_url
        if self._base_url.endswith("/"):
            return f"{self._base_url}v1/chat/completions"
        return f"{self._base_url}/v1/chat/completions"


def _extract_assistant_content(body: Mapping[str, Any]) -> Optional[str]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0] if isinstance(choices[0], Mapping) else None
    if not isinstance(first, Mapping):
        return None
    message = first.get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    return None


def _extract_finish_reason(body: Mapping[str, Any]) -> Optional[str]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    value = first.get("finish_reason")
    if value is None:
        return None
    return str(value)


def _normalize_usage(usage: Any) -> Dict[str, int]:
    if not isinstance(usage, Mapping):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": _to_nonneg_int(usage.get("prompt_tokens")),
        "completion_tokens": _to_nonneg_int(usage.get("completion_tokens")),
        "total_tokens": _to_nonneg_int(usage.get("total_tokens")),
    }


def _to_nonneg_int(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return parsed if parsed >= 0 else 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate_preview(value: Any, *, max_len: int = _RAW_PREVIEW_LEN) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}..."


def _trim_messages_for_context(
    messages: Sequence[Mapping[str, Any]],
    *,
    max_messages: int = _MAX_HISTORY_MESSAGES,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in messages:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role not in _ALLOWED_ROLES or content.strip() == "":
            continue
        rows.append({"role": role, "content": content})
    if len(rows) <= max_messages:
        return rows
    return rows[-max_messages:]


def _conversation_store_key(*, workspace_id: str, user_id: str, conversation_id: str) -> str:
    return f"chat:minimal:{workspace_id}:{user_id}:{conversation_id}"


def _new_conversation_id() -> str:
    return f"conv_{uuid.uuid4().hex}"


def _get_valkey_client() -> Any:
    global _valkey_client
    if _valkey_client is not None:
        return _valkey_client
    if valkey is None:
        return None
    host = str(VALKEY_ADDRESS or "").strip()
    port = str(VALKEY_PORT or "").strip()
    if not host or not port:
        return None
    try:
        _valkey_client = valkey.StrictValkey(host=host, port=port, decode_responses=True)
    except Exception:
        logger.debug("minimal chat valkey init failed", exc_info=True)
        _valkey_client = None
    return _valkey_client


def _safe_validation_errors(exc: ValidationError) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in exc.errors():
        if not isinstance(row, dict):
            rows.append({"message": str(row)})
            continue
        item = dict(row)
        if "ctx" in item and isinstance(item["ctx"], Mapping):
            item["ctx"] = {str(k): str(v) for k, v in item["ctx"].items()}
        rows.append(item)
    return rows


__all__ = ["MinimalChatService", "MinimalChatRequest", "ChatMessage"]

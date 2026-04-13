from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from app.config import (
    QF_FORGE_INSIGHTS_CONVERSATION_TTL_SECONDS,
    QF_FORGE_INSIGHTS_LIST_LIMIT,
    QF_FORGE_INSIGHTS_MAX_CONTEXT_CHARS,
    QF_FORGE_INSIGHTS_MAX_HISTORY_MESSAGES,
    QF_FORGE_INSIGHTS_SUMMARY_ENABLED,
    QF_FORGE_INSIGHTS_SUMMARY_TRIGGER_MESSAGES,
    QF_MINIMAL_CHAT_CONVERSATION_TTL_SECONDS,
    VALKEY_ADDRESS,
    VALKEY_PORT,
    VLLM_BASE_URL,
    VLLM_MODEL,
    VLLM_TIMEOUT,
)
from app.exceptions.forge_error import ForgeError
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
_MAX_SUMMARY_LEN = 5000
_MAX_SUMMARY_LINES = 28
_ALLOWED_ROLES = {"user", "assistant", "system"}
_DEFAULT_HISTORY_LIMIT = 80
_MAX_IN_MEMORY_CONVERSATIONS = 500
_IN_MEMORY_CONV_STORE: Dict[str, Any] = {}
_valkey_client: Any = None

try:
    import valkey  # type: ignore
    from valkey.exceptions import ValkeyError
except ImportError:  # pragma: no cover
    valkey = None
    ValkeyError = None  # type: ignore[assignment]


JSON_PARSE_ERRORS = (TypeError, ValueError, json.JSONDecodeError)
VALKEY_BACKEND_ERRORS = ((OSError, ValkeyError) if ValkeyError is not None else (OSError,))
STORE_FALLBACK_ERRORS = ((ForgeError,) + VALKEY_BACKEND_ERRORS + (RuntimeError, ValueError))


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
        except (TypeError, ValueError) as exc:
            raise ValueError("max_tokens must be an integer") from exc
        if parsed <= 0:
            raise ValueError("max_tokens must be > 0")
        return parsed

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, value: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
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
    ) -> None:
        ...


class HybridConversationStore:
    def __init__(self, *, namespace: str = "minimal", default_ttl_seconds: int = 43200) -> None:
        self._namespace = str(namespace or "minimal").strip().lower() or "minimal"
        self._default_ttl_seconds = max(60, int(default_ttl_seconds or 43200))

    def get_messages(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Optional[List[Dict[str, str]]]:
        convo = self.get_conversation(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id)
        if convo is None:
            return None
        return list(convo.get("messages") or [])

    def save_messages(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        messages: Sequence[Mapping[str, Any]],
    ) -> None:
        now_iso = _utc_now_iso()
        existing = self.get_conversation(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id) or {}
        convo = _normalize_conversation_record(
            {
                "conversation_id": conversation_id,
                "messages": list(messages or []),
                "summary": str(existing.get("summary") or ""),
                "title": existing.get("title"),
                "created_at": str(existing.get("created_at") or now_iso),
                "updated_at": now_iso,
            },
            conversation_id=conversation_id,
        )
        self.save_conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            conversation=convo,
        )

    def get_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        key = _conversation_store_key(
            namespace=self._namespace,
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        payload = self._read(key)
        if payload is None:
            return None
        try:
            raw = json.loads(payload)
        except JSON_PARSE_ERRORS:
            logger.debug("forge insights conversation payload parse failed key=%s", key)
            return None
        if isinstance(raw, list):
            return _normalize_conversation_record({"messages": raw}, conversation_id=conversation_id)
        if isinstance(raw, Mapping):
            return _normalize_conversation_record(raw, conversation_id=conversation_id)
        return None

    def save_conversation(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        conversation: Mapping[str, Any],
    ) -> None:
        key = _conversation_store_key(
            namespace=self._namespace,
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        convo = _normalize_conversation_record(conversation, conversation_id=conversation_id)
        payload = json.dumps(convo, separators=(",", ":"))
        self._write(key, payload)

    def list_conversations(
        self,
        *,
        workspace_id: str,
        user_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        prefix = _conversation_store_prefix(namespace=self._namespace, workspace_id=workspace_id, user_id=user_id)
        keys = self._keys_by_prefix(prefix)
        out: List[Dict[str, Any]] = []
        for key in keys:
            conversation_id = key[len(prefix) :]
            convo = self.get_conversation(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if convo is None:
                continue
            out.append(
                {
                    "conversation_id": conversation_id,
                    "title": convo.get("title"),
                    "last_user_message": convo.get("last_user_message"),
                    "created_at": convo.get("created_at"),
                    "updated_at": convo.get("updated_at"),
                    "message_count": int(convo.get("message_count") or 0),
                    "has_summary": bool(str(convo.get("summary") or "").strip()),
                }
            )
        out.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return out[: max(1, int(limit or 1))]

    def delete_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str) -> bool:
        key = _conversation_store_key(
            namespace=self._namespace,
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        deleted = self._delete(key)
        if not deleted:
            return False
        return True

    def _keys_by_prefix(self, prefix: str) -> List[str]:
        client = _get_valkey_client()
        keys: List[str] = []
        if client is not None:
            try:
                for item in client.scan_iter(match=f"{prefix}*"):
                    if isinstance(item, bytes):
                        token = item.decode("utf-8", errors="ignore")
                    else:
                        token = str(item or "")
                    if token:
                        keys.append(token)
            except VALKEY_BACKEND_ERRORS:
                logger.debug("forge insights valkey scan failed", exc_info=True)
        if not keys:
            _purge_expired_in_memory_entries()
            keys.extend([k for k in _IN_MEMORY_CONV_STORE.keys() if str(k).startswith(prefix)])
        return list(dict.fromkeys(keys))

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
                logger.debug("forge insights valkey read failed", exc_info=True)
        return _read_in_memory_value(key)

    def _write(self, key: str, value: str) -> None:
        client = _get_valkey_client()
        if client is not None:
            try:
                client.setex(key, int(self._default_ttl_seconds), value)
                return
            except VALKEY_BACKEND_ERRORS:
                logger.debug("forge insights valkey write failed", exc_info=True)
        _write_in_memory_value(key, value, ttl_seconds=self._default_ttl_seconds)

    def _delete(self, key: str) -> bool:
        client = _get_valkey_client()
        deleted = False
        if client is not None:
            try:
                deleted = bool(int(client.delete(key) or 0))
            except VALKEY_BACKEND_ERRORS:
                logger.debug("forge insights valkey delete failed", exc_info=True)
        if key in _IN_MEMORY_CONV_STORE:
            _IN_MEMORY_CONV_STORE.pop(key, None)
            deleted = True
        return deleted


class MinimalChatService:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        conversation_store: Optional[ConversationStore] = None,
        conversation_ttl_seconds: Optional[int] = None,
        feature_name: str = "MinimalChat",
        conversation_prefix: str = "conv_",
        conversation_namespace: str = "minimal",
        max_history_messages: Optional[int] = None,
        max_context_chars: Optional[int] = None,
        summary_enabled: Optional[bool] = None,
        summary_trigger_messages: Optional[int] = None,
        list_limit: Optional[int] = None,
        require_existing_conversation: bool = True,
    ) -> None:
        self._base_url = str(base_url or VLLM_BASE_URL or "").strip()
        self._model = str(model or VLLM_MODEL or "").strip() or "qwen"
        self._timeout_seconds = int(timeout_seconds or VLLM_TIMEOUT or 60)
        self._feature_name = str(feature_name or "MinimalChat").strip() or "MinimalChat"
        self._conversation_prefix = str(conversation_prefix or "conv_").strip() or "conv_"
        self._conversation_namespace = str(conversation_namespace or "minimal").strip().lower() or "minimal"

        default_ttl = QF_FORGE_INSIGHTS_CONVERSATION_TTL_SECONDS
        if self._conversation_namespace == "minimal":
            default_ttl = QF_MINIMAL_CHAT_CONVERSATION_TTL_SECONDS
        self._conversation_ttl_seconds = max(60, int(conversation_ttl_seconds or default_ttl or 43200))
        self._conversation_store = conversation_store or HybridConversationStore(
            namespace=self._conversation_namespace,
            default_ttl_seconds=self._conversation_ttl_seconds,
        )
        self._max_history_messages = max(10, int(max_history_messages or QF_FORGE_INSIGHTS_MAX_HISTORY_MESSAGES or _DEFAULT_HISTORY_LIMIT))
        self._max_context_chars = max(2000, int(max_context_chars or QF_FORGE_INSIGHTS_MAX_CONTEXT_CHARS or 24000))
        self._summary_enabled = bool(QF_FORGE_INSIGHTS_SUMMARY_ENABLED if summary_enabled is None else summary_enabled)
        self._summary_trigger_messages = max(8, int(summary_trigger_messages or QF_FORGE_INSIGHTS_SUMMARY_TRIGGER_MESSAGES or 24))
        self._list_limit = max(1, int(list_limit or QF_FORGE_INSIGHTS_LIST_LIMIT or 50))
        self._require_existing_conversation = bool(require_existing_conversation)

    def chat(self, body: Mapping[str, Any], *, workspace_id: str, user_id: str) -> Dict[str, Any]:
        try:
            req = MinimalChatRequest.model_validate(dict(body or {}))
        except ValidationError as exc:
            raise ForgeError(
                "Invalid chat request",
                status_code=400,
                details={"errors": _safe_validation_errors(exc)},
            ) from exc
        except ValueError as exc:
            raise ForgeError("Invalid chat request", status_code=400, details={"message": str(exc)}) from exc

        conversation_id = req.conversation_id or _new_conversation_id(prefix=self._conversation_prefix)
        prior_conversation = self._get_conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if req.conversation_id and prior_conversation is None and self._require_existing_conversation:
            raise ForgeError("Conversation not found", status_code=404, details={"conversation_id": conversation_id})

        conversation = prior_conversation or _new_conversation_record(conversation_id=conversation_id)
        history = list(conversation.get("messages") or [])
        summary = str(conversation.get("summary") or "")
        new_messages = [m.model_dump(mode="json") for m in req.messages]
        provider_messages = _build_provider_messages(
            summary=summary,
            messages=history + new_messages,
            max_messages=self._max_history_messages,
            max_context_chars=self._max_context_chars,
            feature_name=self._feature_name,
        )

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
            raise ForgeError(
                "Malformed provider response",
                status_code=502,
                details={"message": "missing assistant message content"},
            )

        provider_body = trace["body"]
        usage = _normalize_usage(provider_body.get("usage"))
        finish_reason = _extract_finish_reason(provider_body)
        provider_model = str(provider_body.get("model") or self._model).strip() or self._model

        response: Dict[str, Any] = {
            "id": str(provider_body.get("id") or f"chatcmpl_local_{uuid.uuid4().hex[:12]}"),
            "model": provider_model,
            "created_at": _utc_now_iso(),
            "conversation_id": conversation_id,
            "message": {"role": "assistant", "content": assistant_content},
            "usage": usage,
            "debug": None,
        }

        combined_messages = history + new_messages + [{"role": "assistant", "content": assistant_content}]
        compressed_summary, compressed_messages, was_compacted = _compact_conversation_context(
            summary=summary,
            messages=combined_messages,
            max_messages=self._max_history_messages,
            max_context_chars=self._max_context_chars,
            summary_enabled=self._summary_enabled,
            summary_trigger_messages=self._summary_trigger_messages,
        )
        updated_conversation = _normalize_conversation_record(
            {
                "conversation_id": conversation_id,
                "messages": compressed_messages,
                "summary": compressed_summary,
                "created_at": conversation.get("created_at"),
                "title": conversation.get("title") or _derive_conversation_title(history + new_messages),
                "updated_at": _utc_now_iso(),
            },
            conversation_id=conversation_id,
        )
        self._save_conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            conversation=updated_conversation,
        )

        if req.debug:
            response["debug"] = {
                "feature": self._feature_name,
                "provider_model": provider_model,
                "finish_reason": finish_reason,
                "request_preview": _truncate_preview(provider_payload),
                "response_preview": _truncate_preview(trace.get("raw_text")),
                "status_code": trace.get("status_code"),
                "conversation_history_count": int(updated_conversation.get("message_count") or 0),
                "conversation_compacted": bool(was_compacted),
                "conversation_has_summary": bool(str(updated_conversation.get("summary") or "").strip()),
            }
        return response

    def list_conversations(self, *, workspace_id: str, user_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
        capped = max(1, min(int(limit or self._list_limit), 200))
        items = self._list_store_conversations(workspace_id=workspace_id, user_id=user_id, limit=capped)
        return {"feature": self._feature_name, "items": items, "count": len(items)}

    def get_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        token = str(conversation_id or "").strip()
        if token == "":
            raise ForgeError("conversation_id is required", status_code=400)
        convo = self._get_conversation(workspace_id=workspace_id, user_id=user_id, conversation_id=token)
        if convo is None:
            raise ForgeError("Conversation not found", status_code=404, details={"conversation_id": token})
        out = dict(convo)
        out["feature"] = self._feature_name
        return out

    def reset_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        token = str(conversation_id or "").strip()
        if token == "":
            raise ForgeError("conversation_id is required", status_code=400)
        deleted = self._delete_store_conversation(workspace_id=workspace_id, user_id=user_id, conversation_id=token)
        if not deleted:
            raise ForgeError("Conversation not found", status_code=404, details={"conversation_id": token})
        return {"feature": self._feature_name, "conversation_id": token, "deleted": True}

    def _call_provider(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        chat_url = self._chat_url()
        request_id = new_llm_request_id()
        client_name = f"{self._feature_name}ChatService"
        log_llm_request(
            logger,
            client_name=client_name,
            request_id=request_id,
            method="POST",
            url=chat_url,
            payload=dict(payload),
        )
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(chat_url, json=dict(payload))
        except httpx.HTTPError as exc:
            log_llm_exception(
                logger,
                client_name=client_name,
                request_id=request_id,
                method="POST",
                url=chat_url,
                message=str(exc),
            )
            raise ForgeError("Chat provider request failed", status_code=502, details={"message": str(exc)}) from exc

        raw_text = resp.text
        log_llm_response(
            logger,
            client_name=client_name,
            request_id=request_id,
            status_code=resp.status_code,
            response_text=raw_text,
        )
        if resp.status_code >= 400:
            logger.warning("forge insights provider http_error status=%s", resp.status_code)
            raise ForgeError(
                "Chat provider request failed",
                status_code=502,
                details={
                    "provider_status": resp.status_code,
                    "provider_response": _truncate_preview(raw_text),
                },
            )

        try:
            body = resp.json()
        except JSON_PARSE_ERRORS as exc:
            raise ForgeError(
                "Malformed provider response",
                status_code=502,
                details={"message": f"response_json_parse_error:{str(exc)}"},
            ) from exc
        if not isinstance(body, dict):
            raise ForgeError("Malformed provider response", status_code=502, details={"message": "response must be object"})
        return {"status_code": resp.status_code, "body": body, "raw_text": raw_text}

    def _chat_url(self) -> str:
        if self._base_url.endswith("/v1/chat/completions"):
            return self._base_url
        if self._base_url.endswith("/"):
            return f"{self._base_url}v1/chat/completions"
        return f"{self._base_url}/v1/chat/completions"

    def _get_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        get_conv = getattr(self._conversation_store, "get_conversation", None)
        if callable(get_conv):
            convo = get_conv(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id)
            if convo is None:
                return None
            return _normalize_conversation_record(convo, conversation_id=conversation_id)
        get_messages = getattr(self._conversation_store, "get_messages", None)
        if not callable(get_messages):
            return None
        rows = get_messages(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id)
        if rows is None:
            return None
        return _normalize_conversation_record({"messages": rows}, conversation_id=conversation_id)

    def _save_conversation(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        conversation: Mapping[str, Any],
    ) -> None:
        save_conv = getattr(self._conversation_store, "save_conversation", None)
        if callable(save_conv):
            save_conv(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
                conversation=conversation,
            )
            return
        save_messages = getattr(self._conversation_store, "save_messages", None)
        if callable(save_messages):
            save_messages(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
                messages=list(conversation.get("messages") or []),
            )
            return
        raise ForgeError("Conversation store does not support saving", status_code=500)

    def _list_store_conversations(self, *, workspace_id: str, user_id: str, limit: int) -> List[Dict[str, Any]]:
        list_fn = getattr(self._conversation_store, "list_conversations", None)
        if not callable(list_fn):
            return []
        try:
            rows = list_fn(workspace_id=workspace_id, user_id=user_id, limit=limit)
        except STORE_FALLBACK_ERRORS:
            logger.exception("forge insights list conversations failed")
            return []
        out: List[Dict[str, Any]] = []
        for row in rows or []:
            if isinstance(row, Mapping):
                out.append(dict(row))
        return out

    def _delete_store_conversation(self, *, workspace_id: str, user_id: str, conversation_id: str) -> bool:
        delete_fn = getattr(self._conversation_store, "delete_conversation", None)
        if callable(delete_fn):
            try:
                return bool(delete_fn(workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id))
            except STORE_FALLBACK_ERRORS:
                logger.exception("forge insights delete conversation failed")
                return False
        return False


class ForgeInsightsChatService(MinimalChatService):
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        conversation_store: Optional[ConversationStore] = None,
        conversation_ttl_seconds: Optional[int] = None,
    ) -> None:
        if conversation_store is None:
            from app.services.chat.forge_insights_conversation_store import ForgeInsightsConversationStore

            conversation_store = ForgeInsightsConversationStore()
        super().__init__(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            conversation_store=conversation_store,
            conversation_ttl_seconds=conversation_ttl_seconds,
            feature_name="ForgeInsights",
            conversation_prefix="fi_",
            conversation_namespace="forge_insights",
            require_existing_conversation=False,
        )


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
    except (TypeError, ValueError):
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
    max_messages: int = _DEFAULT_HISTORY_LIMIT,
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


def _build_provider_messages(
    *,
    summary: str,
    messages: Sequence[Mapping[str, Any]],
    max_messages: int,
    max_context_chars: int,
    feature_name: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    summary_text = str(summary or "").strip()
    if summary_text:
        rows.append(
            {
                "role": "system",
                "content": (
                    f"{feature_name} conversation summary for context. "
                    "Use this as prior context and continue the same thread.\n"
                    f"{summary_text}"
                ),
            }
        )
    rows.extend(_trim_messages_for_context(messages, max_messages=max_messages))
    return _enforce_context_char_budget(rows, max_chars=max_context_chars)


def _compact_conversation_context(
    *,
    summary: str,
    messages: Sequence[Mapping[str, Any]],
    max_messages: int,
    max_context_chars: int,
    summary_enabled: bool,
    summary_trigger_messages: int,
) -> tuple[str, List[Dict[str, str]], bool]:
    rows = _trim_messages_for_context(messages, max_messages=max(8, max_messages * 2))
    summary_text = str(summary or "").strip()
    needs_compaction = len(rows) > max_messages or _message_chars(rows) > max_context_chars
    if not summary_enabled:
        final_rows = _trim_messages_for_context(rows, max_messages=max_messages)
        return summary_text, final_rows, needs_compaction
    if not needs_compaction and len(rows) <= summary_trigger_messages:
        return summary_text, rows, False

    keep_tail = max(8, min(max_messages, summary_trigger_messages))
    old_rows = rows[:-keep_tail] if len(rows) > keep_tail else []
    tail_rows = rows[-keep_tail:] if old_rows else rows
    if old_rows:
        delta = _summarize_messages(old_rows)
        summary_text = _merge_summaries(summary_text, delta)
    compact_rows = _trim_messages_for_context(tail_rows, max_messages=max_messages)
    compact_rows = _enforce_context_char_budget(compact_rows, max_chars=max_context_chars)
    return summary_text, compact_rows, True


def _summarize_messages(messages: Sequence[Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for item in messages:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or content == "":
            continue
        prefix = "User" if role == "user" else "Assistant"
        lines.append(f"{prefix}: {_truncate_preview(content, max_len=220)}")
        if len(lines) >= _MAX_SUMMARY_LINES:
            break
    if not lines:
        return ""
    return "\n".join(lines)


def _merge_summaries(existing: str, delta: str) -> str:
    left = str(existing or "").strip()
    right = str(delta or "").strip()
    if left and right:
        merged = f"{left}\n{right}"
    else:
        merged = left or right
    return _truncate_preview(merged, max_len=_MAX_SUMMARY_LEN)


def _message_chars(messages: Sequence[Mapping[str, Any]]) -> int:
    return sum(len(str(item.get("content") or "")) for item in messages if isinstance(item, Mapping))


def _enforce_context_char_budget(messages: Sequence[Mapping[str, Any]], *, max_chars: int) -> List[Dict[str, str]]:
    rows = _trim_messages_for_context(messages, max_messages=max(1, len(list(messages))))
    if _message_chars(rows) <= max_chars:
        return rows
    system_rows = [row for row in rows if row.get("role") == "system"]
    tail_rows = [row for row in rows if row.get("role") != "system"]
    while tail_rows and (_message_chars(system_rows + tail_rows) > max_chars):
        tail_rows.pop(0)
    return system_rows + tail_rows


def _new_conversation_record(*, conversation_id: str) -> Dict[str, Any]:
    now_iso = _utc_now_iso()
    return {
        "conversation_id": conversation_id,
        "messages": [],
        "summary": "",
        "title": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "message_count": 0,
        "last_user_message": None,
    }


def _normalize_conversation_record(raw: Mapping[str, Any], *, conversation_id: str) -> Dict[str, Any]:
    now_iso = _utc_now_iso()
    rows = _trim_messages_for_context(list(raw.get("messages") or []), max_messages=max(1, 10_000))
    created_at = str(raw.get("created_at") or now_iso)
    updated_at = str(raw.get("updated_at") or now_iso)
    title = raw.get("title")
    summary = _truncate_preview(str(raw.get("summary") or "").strip(), max_len=_MAX_SUMMARY_LEN)
    out = {
        "conversation_id": str(raw.get("conversation_id") or conversation_id),
        "messages": rows,
        "summary": summary,
        "title": str(title).strip() if isinstance(title, str) and str(title).strip() else None,
        "created_at": created_at,
        "updated_at": updated_at,
        "message_count": len(rows),
        "last_user_message": _last_user_message(rows),
    }
    if out["title"] is None:
        out["title"] = _derive_conversation_title(rows)
    return out


def _derive_conversation_title(messages: Sequence[Mapping[str, Any]]) -> Optional[str]:
    for row in messages:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("role") or "").strip().lower() != "user":
            continue
        text = " ".join(str(row.get("content") or "").split()).strip()
        if text == "":
            continue
        return _truncate_preview(text, max_len=80)
    return None


def _last_user_message(messages: Sequence[Mapping[str, Any]]) -> Optional[str]:
    for row in reversed(list(messages)):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("role") or "").strip().lower() != "user":
            continue
        text = " ".join(str(row.get("content") or "").split()).strip()
        if text:
            return _truncate_preview(text, max_len=240)
    return None


def _conversation_store_prefix(*, namespace: str, workspace_id: str, user_id: str) -> str:
    return f"chat:{namespace}:{workspace_id}:{user_id}:"


def _conversation_store_key(*, namespace: str, workspace_id: str, user_id: str, conversation_id: str) -> str:
    return f"{_conversation_store_prefix(namespace=namespace, workspace_id=workspace_id, user_id=user_id)}{conversation_id}"


def _new_conversation_id(*, prefix: str = "conv_") -> str:
    return f"{prefix}{uuid.uuid4().hex}"


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
    except VALKEY_BACKEND_ERRORS:
        logger.debug("forge insights valkey init failed", exc_info=True)
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


def _read_in_memory_value(key: str) -> Optional[str]:
    _purge_expired_in_memory_entries()
    raw = _IN_MEMORY_CONV_STORE.get(key)
    if raw is None:
        return None
    entry = _normalize_in_memory_entry(raw)
    if entry is None:
        _IN_MEMORY_CONV_STORE.pop(key, None)
        return None
    if _is_in_memory_entry_expired(entry):
        _IN_MEMORY_CONV_STORE.pop(key, None)
        return None
    return str(entry.get("value") or "")


def _write_in_memory_value(key: str, value: str, *, ttl_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(1, int(ttl_seconds or 1)))
    _IN_MEMORY_CONV_STORE[key] = {
        "value": value,
        "stored_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }
    _trim_in_memory_store(max_entries=_MAX_IN_MEMORY_CONVERSATIONS)


def _purge_expired_in_memory_entries() -> None:
    expired_keys = [
        key
        for key, raw in list(_IN_MEMORY_CONV_STORE.items())
        if (entry := _normalize_in_memory_entry(raw)) is None or _is_in_memory_entry_expired(entry)
    ]
    for key in expired_keys:
        _IN_MEMORY_CONV_STORE.pop(key, None)


def _trim_in_memory_store(*, max_entries: int) -> None:
    _purge_expired_in_memory_entries()
    overflow = len(_IN_MEMORY_CONV_STORE) - max(1, int(max_entries or 1))
    if overflow <= 0:
        return
    ranked: List[tuple[datetime, str]] = []
    for key, raw in list(_IN_MEMORY_CONV_STORE.items()):
        entry = _normalize_in_memory_entry(raw)
        if entry is None:
            ranked.append((datetime.min.replace(tzinfo=timezone.utc), key))
            continue
        stored_at = _parse_utc_datetime(entry.get("stored_at")) or datetime.min.replace(tzinfo=timezone.utc)
        ranked.append((stored_at, key))
    ranked.sort(key=lambda item: (item[0], item[1]))
    for _, key in ranked[:overflow]:
        _IN_MEMORY_CONV_STORE.pop(key, None)


def _normalize_in_memory_entry(raw: Any) -> Optional[Dict[str, str]]:
    if isinstance(raw, str):
        return {"value": raw, "stored_at": "", "expires_at": ""}
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("value")
    if not isinstance(value, str):
        return None
    return {
        "value": value,
        "stored_at": str(raw.get("stored_at") or ""),
        "expires_at": str(raw.get("expires_at") or ""),
    }


def _is_in_memory_entry_expired(entry: Mapping[str, Any]) -> bool:
    expires_at = _parse_utc_datetime(entry.get("expires_at"))
    if expires_at is None:
        return False
    return expires_at <= datetime.now(timezone.utc)


def _parse_utc_datetime(value: Any) -> Optional[datetime]:
    token = str(value or "").strip()
    if token == "":
        return None
    try:
        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = ["MinimalChatService", "ForgeInsightsChatService", "MinimalChatRequest", "ChatMessage"]

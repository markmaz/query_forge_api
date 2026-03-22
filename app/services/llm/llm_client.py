from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, Mapping, Optional

import httpx

from app.config import SEMANTIC_LLM_ENDPOINT, SEMANTIC_LLM_MODEL, SEMANTIC_LLM_TIMEOUT_SECONDS
from app.exceptions.forge_error import ForgeError
from app.services.llm.io_logging import (
    log_llm_exception,
    log_llm_request,
    log_llm_response,
    new_llm_request_id,
)

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        api_key: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        raw_endpoint = str(endpoint if endpoint is not None else SEMANTIC_LLM_ENDPOINT)
        normalized_endpoint = raw_endpoint.strip().strip('"').strip("'")
        if normalized_endpoint.startswith("="):
            logger.warning("LLM endpoint had leading '=' characters; normalizing endpoint value")
            normalized_endpoint = normalized_endpoint.lstrip("=").strip()
        self._endpoint = normalized_endpoint
        self._model = (model or SEMANTIC_LLM_MODEL).strip()
        self._timeout_seconds = int(timeout_seconds or SEMANTIC_LLM_TIMEOUT_SECONDS)
        self._headers = self._build_headers(api_key=api_key, headers=headers)

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: Any = True,
        retry_invalid_schema: bool = True,
        validator: Optional[Callable[[Dict[str, Any]], bool]] = None,
        max_tokens: Optional[int] = None,
        extra_params: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if max_tokens is None:
            first = self.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=response_format,
                extra_params=extra_params,
            )
        else:
            first = self.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=response_format,
                max_tokens=max_tokens,
                extra_params=extra_params,
            )
        parsed = first.get("parsed") if isinstance(first.get("parsed"), dict) else None
        is_valid = parsed is not None and (validator(parsed) if validator is not None else True)
        second: Optional[Dict[str, Any]] = None
        if not is_valid and retry_invalid_schema:
            repair_user = (
                "Return valid JSON only. Your previous output was invalid JSON. "
                f"Previous output: {str(first.get('content') or first.get('raw_text') or '')[:3000]}"
            )
            if max_tokens is None:
                second = self.chat_json_with_trace(
                    system_prompt=system_prompt,
                    user_prompt=repair_user,
                    response_format=response_format,
                    extra_params=extra_params,
                )
            else:
                second = self.chat_json_with_trace(
                    system_prompt=system_prompt,
                    user_prompt=repair_user,
                    response_format=response_format,
                    max_tokens=max_tokens,
                    extra_params=extra_params,
                )
            parsed = second.get("parsed") if isinstance(second.get("parsed"), dict) else None
            is_valid = parsed is not None and (validator(parsed) if validator is not None else True)
        if not is_valid or parsed is None:
            raise ForgeError(
                "Invalid model response JSON",
                status_code=500,
                details={
                    "attempt1": self._trace_summary(first),
                    "attempt2": self._trace_summary(second) if second is not None else None,
                },
            )
        return parsed

    def chat_json_with_trace(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: Any = True,
        max_tokens: Optional[int] = None,
        extra_params: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._chat_once_with_trace(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
            max_tokens=max_tokens,
            extra_params=extra_params,
        )

    def _chat_once(self, *, system_prompt: str, user_prompt: str, response_format: Any) -> str:
        trace = self._chat_once_with_trace(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
        )
        content = trace.get("content")
        if isinstance(content, str) and content.strip() != "":
            return content
        raise ForgeError("LLM response missing content", status_code=502, details={"trace": trace})

    def _chat_once_with_trace(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: Any,
        max_tokens: Optional[int] = None,
        extra_params: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        chat_url = self._chat_url()
        token_param_name = self._completion_token_param_name()
        temperature_value = self._temperature_value()
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if temperature_value is not None:
            payload["temperature"] = temperature_value
        if max_tokens is not None:
            try:
                mt = int(max_tokens)
            except Exception:
                mt = 0
            if mt > 0:
                payload[token_param_name] = mt
        normalized_response_format = self._normalize_response_format(response_format)
        if normalized_response_format is not None:
            payload["response_format"] = normalized_response_format
        if isinstance(extra_params, Mapping):
            for key, value in extra_params.items():
                k = str(key or "").strip()
                if k == "" or k in {"model", "messages", "prompt"} or value is None:
                    continue
                payload[k] = value

        request_id = new_llm_request_id()
        log_llm_request(
            logger,
            client_name="LLMClient.chat",
            request_id=request_id,
            method="POST",
            url=chat_url,
            payload=payload,
        )
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(chat_url, json=payload, headers=self._headers or None)
                raw_text = resp.text
                log_llm_response(
                    logger,
                    client_name="LLMClient.chat",
                    request_id=request_id,
                    status_code=resp.status_code,
                    response_text=raw_text,
                )
                parsed_body: Optional[Dict[str, Any]] = None
                content: Optional[str] = None
                error: Optional[str] = None
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        parsed_body = body
                    content = self._extract_chat_content(body if isinstance(body, dict) else {})
                    finish_reason = self._extract_finish_reason(body if isinstance(body, dict) else {})
                except Exception as exc:
                    error = f"response_json_parse_error:{str(exc)}"
                    finish_reason = None

                if resp.status_code < 400:
                    if content is not None:
                        parsed_json = self._parse_json(content)
                        return {
                            "raw_text": raw_text,
                            "parsed": parsed_json,
                            "content": content,
                            "finish_reason": finish_reason,
                            "error": error,
                        }
                fallback = self._fallback_simple_with_trace(
                    client=client,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    extra_params=extra_params,
                )
                if fallback.get("error"):
                    return {
                        "raw_text": raw_text,
                        "parsed": parsed_body,
                        "content": content,
                        "error": fallback.get("error"),
                    }
                return fallback
        except Exception as exc:
            log_llm_exception(
                logger,
                client_name="LLMClient.chat",
                request_id=request_id,
                method="POST",
                url=chat_url,
                message=str(exc),
            )
            if isinstance(exc, httpx.ConnectError):
                raise ForgeError(
                    "LLM provider unavailable",
                    status_code=503,
                    details={
                        "message": str(exc),
                        "chat_url": chat_url,
                        "endpoint": self._endpoint,
                        "model": self._model,
                        "hint": "Ensure the LLM server is running and reachable from the API host",
                    },
                ) from exc
            if isinstance(exc, httpx.TimeoutException):
                raise ForgeError(
                    "LLM request timed out",
                    status_code=504,
                    details={
                        "message": str(exc),
                        "chat_url": chat_url,
                        "timeout_seconds": self._timeout_seconds,
                        "model": self._model,
                    },
                ) from exc
            raise ForgeError(
                "LLM request failed",
                status_code=502,
                details={
                    "message": str(exc),
                    "chat_url": chat_url,
                    "model": self._model,
                },
            ) from exc

    def _fallback_simple_with_trace(
        self,
        *,
        client: httpx.Client,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        response_format: Any = True,
        extra_params: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        target_url = self._endpoint
        payload: Dict[str, Any]
        if self._looks_like_chat_completions_url(target_url):
            temperature_value = self._temperature_value()
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            if temperature_value is not None:
                payload["temperature"] = temperature_value
            if max_tokens is not None:
                try:
                    mt = int(max_tokens)
                except Exception:
                    mt = 0
                if mt > 0:
                    payload[self._completion_token_param_name()] = mt
            normalized_response_format = self._normalize_response_format(response_format)
            if normalized_response_format is not None:
                payload["response_format"] = normalized_response_format
        else:
            payload = {
                "model": self._model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
            }
            temperature_value = self._temperature_value()
            if temperature_value is not None:
                payload["temperature"] = temperature_value
            if max_tokens is not None:
                try:
                    mt = int(max_tokens)
                except Exception:
                    mt = 0
                if mt > 0:
                    payload["max_tokens"] = mt
        if isinstance(extra_params, Mapping):
            for key, value in extra_params.items():
                k = str(key or "").strip()
                if k == "" or k in {"model", "messages", "prompt"} or value is None:
                    continue
                payload[k] = value
        request_id = new_llm_request_id()
        log_llm_request(
            logger,
            client_name="LLMClient.fallback",
            request_id=request_id,
            method="POST",
            url=target_url,
            payload=payload,
        )
        resp = client.post(target_url, json=payload, headers=self._headers or None)
        raw_text = resp.text
        log_llm_response(
            logger,
            client_name="LLMClient.fallback",
            request_id=request_id,
            status_code=resp.status_code,
            response_text=raw_text,
        )
        if resp.status_code >= 400:
            return {
                "raw_text": raw_text,
                "parsed": None,
                "content": None,
                "error": f"http_status:{resp.status_code}",
            }

        try:
            body = resp.json()
        except Exception as exc:
            return {
                "raw_text": raw_text,
                "parsed": None,
                "content": None,
                "error": f"response_json_parse_error:{str(exc)}",
            }

        content: Optional[str] = None
        for key in ("output_text", "text", "content"):
            val = body.get(key)
            if isinstance(val, str) and val.strip() != "":
                content = val
                break
        if content is None and isinstance(body.get("choices"), list):
            content = self._extract_chat_content(body)

        if content is None:
            return {
                "raw_text": raw_text,
                "parsed": body if isinstance(body, dict) else None,
                "content": None,
                "error": "missing_content",
            }
        return {
            "raw_text": raw_text,
            "parsed": self._parse_json(content),
            "content": content,
            "error": None,
        }

    def _fallback_simple(self, *, client: httpx.Client, system_prompt: str, user_prompt: str) -> str:
        trace = self._fallback_simple_with_trace(client=client, system_prompt=system_prompt, user_prompt=user_prompt)
        content = trace.get("content")
        if isinstance(content, str) and content.strip() != "":
            return content
        raise ForgeError("LLM response missing content", status_code=502, details={"trace": trace})

    def _chat_url(self) -> str:
        if self._endpoint.endswith("/v1/chat/completions"):
            return self._endpoint
        if self._endpoint.endswith("/v1"):
            return f"{self._endpoint}/chat/completions"
        if self._endpoint.endswith("/v1/"):
            return f"{self._endpoint}chat/completions"
        if self._endpoint.endswith("/"):
            return f"{self._endpoint}v1/chat/completions"
        return f"{self._endpoint}/v1/chat/completions"

    def _completion_token_param_name(self) -> str:
        model = str(self._model or "").strip().lower()
        if model.startswith("gpt-5"):
            return "max_completion_tokens"
        return "max_tokens"

    def _temperature_value(self) -> Optional[int]:
        model = str(self._model or "").strip().lower()
        if model.startswith("gpt-5"):
            return None
        return 0

    @staticmethod
    def _normalize_response_format(value: Any) -> Optional[Dict[str, Any]]:
        if value in (None, False):
            return None
        if value is True:
            return {"type": "json_object"}
        if isinstance(value, Mapping):
            return dict(value)
        return {"type": "json_object"}

    @staticmethod
    def _looks_like_chat_completions_url(url: str) -> bool:
        token = str(url or "").strip().lower()
        return token.endswith("/v1/chat/completions")

    @staticmethod
    def _build_headers(
        *,
        api_key: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, str]:
        out: Dict[str, str] = {}
        if isinstance(headers, Mapping):
            for key, value in headers.items():
                k = str(key or "").strip()
                v = str(value or "").strip()
                if k and v:
                    out[k] = v
        if "Authorization" in out:
            return out
        token = str(api_key if api_key is not None else os.getenv("SEMANTIC_LLM_API_KEY", "")).strip()
        if token:
            out["Authorization"] = f"Bearer {token}"
        return out

    @staticmethod
    def _extract_chat_content(body: Dict[str, Any]) -> Optional[str]:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [p.get("text") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
            if parts:
                return "\n".join(parts)
        return None

    @staticmethod
    def _extract_finish_reason(body: Dict[str, Any]) -> Optional[str]:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        reason = choices[0].get("finish_reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
        return None

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, Any]]:
        text = str(content or "").strip()
        if text == "":
            return None

        parsed = LLMClient._try_parse_obj(text)
        if parsed is not None:
            return parsed

        # Handle fenced JSON blocks.
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, flags=re.IGNORECASE)
        if fenced:
            parsed = LLMClient._try_parse_obj(fenced.group(1).strip())
            if parsed is not None:
                return parsed

        # Handle prose + JSON payload output.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = LLMClient._try_parse_obj(text[start : end + 1].strip())
            if parsed is not None:
                return parsed

        return None

    @staticmethod
    def _try_parse_obj(content: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            return None
        except Exception:
            return None

    @staticmethod
    def _trace_summary(trace: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(trace, dict):
            return None

        parsed = trace.get("parsed")
        provider_error = None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            provider_error = parsed.get("error")

        return {
            "error": trace.get("error"),
            "finish_reason": trace.get("finish_reason"),
            "provider_error": provider_error,
            "content_preview": str(trace.get("content") or "")[:500],
            "raw_text_preview": str(trace.get("raw_text") or "")[:500],
        }

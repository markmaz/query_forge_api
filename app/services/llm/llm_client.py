from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional

import httpx

from app.config import SEMANTIC_LLM_ENDPOINT, SEMANTIC_LLM_MODEL, SEMANTIC_LLM_TIMEOUT_SECONDS
from app.exceptions.service_error import ServiceError


class LLMClient:
    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        self._endpoint = (endpoint or SEMANTIC_LLM_ENDPOINT).strip()
        self._model = (model or SEMANTIC_LLM_MODEL).strip()
        self._timeout_seconds = int(timeout_seconds or SEMANTIC_LLM_TIMEOUT_SECONDS)

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: bool = True,
        retry_invalid_schema: bool = True,
        validator: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        first = self.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
        )
        parsed = first.get("parsed") if isinstance(first.get("parsed"), dict) else None
        is_valid = parsed is not None and (validator(parsed) if validator is not None else True)
        second: Optional[Dict[str, Any]] = None
        if not is_valid and retry_invalid_schema:
            repair_user = (
                "Return valid JSON only. Your previous output was invalid JSON. "
                f"Previous output: {str(first.get('content') or first.get('raw_text') or '')[:3000]}"
            )
            second = self.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=repair_user,
                response_format=response_format,
            )
            parsed = second.get("parsed") if isinstance(second.get("parsed"), dict) else None
            is_valid = parsed is not None and (validator(parsed) if validator is not None else True)
        if not is_valid or parsed is None:
            raise ServiceError(
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
        response_format: bool = True,
    ) -> Dict[str, Any]:
        return self._chat_once_with_trace(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
        )

    def _chat_once(self, *, system_prompt: str, user_prompt: str, response_format: bool) -> str:
        trace = self._chat_once_with_trace(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
        )
        content = trace.get("content")
        if isinstance(content, str) and content.strip() != "":
            return content
        raise ServiceError("LLM response missing content", status_code=502, details={"trace": trace})

    def _chat_once_with_trace(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: bool,
    ) -> Dict[str, Any]:
        chat_url = self._chat_url()
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                resp = client.post(chat_url, json=payload)
                raw_text = resp.text
                parsed_body: Optional[Dict[str, Any]] = None
                content: Optional[str] = None
                error: Optional[str] = None
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        parsed_body = body
                    content = self._extract_chat_content(body if isinstance(body, dict) else {})
                except Exception as exc:
                    error = f"response_json_parse_error:{str(exc)}"

                if resp.status_code < 400:
                    if content is not None:
                        parsed_json = self._parse_json(content)
                        return {
                            "raw_text": raw_text,
                            "parsed": parsed_json,
                            "content": content,
                            "error": error,
                        }
                fallback = self._fallback_simple_with_trace(client=client, system_prompt=system_prompt, user_prompt=user_prompt)
                if fallback.get("error"):
                    return {
                        "raw_text": raw_text,
                        "parsed": parsed_body,
                        "content": content,
                        "error": fallback.get("error"),
                    }
                return fallback
        except Exception as exc:
            raise ServiceError("LLM request failed", status_code=502, details={"message": str(exc)}) from exc

    def _fallback_simple_with_trace(
        self,
        *,
        client: httpx.Client,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        payload = {
            "model": self._model,
            "temperature": 0,
            "prompt": f"{system_prompt}\n\n{user_prompt}",
        }
        resp = client.post(self._endpoint, json=payload)
        raw_text = resp.text
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
        raise ServiceError("LLM response missing content", status_code=502, details={"trace": trace})

    def _chat_url(self) -> str:
        if self._endpoint.endswith("/v1/chat/completions"):
            return self._endpoint
        if self._endpoint.endswith("/"):
            return f"{self._endpoint}v1/chat/completions"
        return f"{self._endpoint}/v1/chat/completions"

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
            "provider_error": provider_error,
            "content_preview": str(trace.get("content") or "")[:500],
            "raw_text_preview": str(trace.get("raw_text") or "")[:500],
        }

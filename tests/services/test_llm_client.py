from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.llm.llm_client import LLMClient


class _FakeLLMClient(LLMClient):
    def __init__(self, traces):
        super().__init__(endpoint="http://localhost:8000", model="qwen25-7b", timeout_seconds=30)
        self._traces = list(traces)

    def chat_json_with_trace(self, *, system_prompt: str, user_prompt: str, response_format: bool = True):
        del system_prompt, user_prompt, response_format
        if self._traces:
            return self._traces.pop(0)
        return {"raw_text": "", "parsed": None, "content": None, "error": "missing_trace"}


def test_parse_json_accepts_fenced_object() -> None:
    parsed = LLMClient._parse_json("```json\n{\"sql_json\": {\"version\": 1}}\n```")
    assert parsed == {"sql_json": {"version": 1}}


def test_chat_json_retry_recovers_from_invalid_first_attempt() -> None:
    client = _FakeLLMClient(
        traces=[
            {"raw_text": "not-json", "parsed": None, "content": "not-json", "error": "invalid"},
            {"raw_text": "{\"sql_json\": {\"version\": 1}}", "parsed": {"sql_json": {"version": 1}}, "content": "{\"sql_json\": {\"version\": 1}}", "error": None},
        ]
    )

    result = client.chat_json(
        system_prompt="sys",
        user_prompt="usr",
        response_format=True,
        retry_invalid_schema=True,
        validator=lambda body: isinstance(body.get("sql_json"), dict),
    )
    assert result["sql_json"]["version"] == 1


def test_chat_json_invalid_response_includes_attempt_details() -> None:
    provider_error = {
        "message": "This model's maximum context length is 8192 tokens.",
        "param": "input_tokens",
        "code": 400,
    }
    client = _FakeLLMClient(
        traces=[
            {
                "raw_text": "{\"error\": {\"message\": \"too many tokens\"}}",
                "parsed": {"error": provider_error},
                "content": "{\"error\": {\"message\": \"too many tokens\"}}",
                "error": "schema_validation_error:missing",
            }
        ]
    )

    with pytest.raises(ServiceError) as exc:
        client.chat_json(
            system_prompt="sys",
            user_prompt="usr",
            response_format=True,
            retry_invalid_schema=False,
            validator=lambda body: isinstance(body.get("sql_json"), dict),
        )

    assert exc.value.message == "Invalid model response JSON"
    assert exc.value.details["attempt1"]["provider_error"]["param"] == "input_tokens"
    assert exc.value.details["attempt2"] is None

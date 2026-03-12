from __future__ import annotations

import httpx
import pytest

from app.exceptions.forge_error import ForgeError
from app.services.llm.llm_client import LLMClient


class _FakeLLMClient(LLMClient):
    def __init__(self, traces):
        super().__init__(endpoint="http://localhost:8000", model="qwen25-7b", timeout_seconds=30)
        self._traces = list(traces)

    def chat_json_with_trace(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: bool = True,
        max_tokens=None,
        extra_params=None,
    ):
        del system_prompt, user_prompt, response_format, max_tokens, extra_params
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

    with pytest.raises(ForgeError) as exc:
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


def test_chat_json_with_trace_connect_error_returns_actionable_service_error(monkeypatch) -> None:
    class _BrokenClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url, json=None, headers=None):
            del json, headers
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", _BrokenClient)
    client = LLMClient(endpoint="http://localhost:8000", model="qwen25-7b", timeout_seconds=1)

    with pytest.raises(ForgeError) as exc:
        client.chat_json_with_trace(system_prompt="sys", user_prompt="usr", response_format=True)

    assert exc.value.message == "LLM provider unavailable"
    assert exc.value.status_code == 503
    assert exc.value.details["chat_url"].endswith("/v1/chat/completions")
    assert "Ensure the LLM server is running" in str(exc.value.details.get("hint") or "")


def test_chat_json_with_trace_timeout_returns_gateway_timeout(monkeypatch) -> None:
    class _TimeoutClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url, json=None, headers=None):
            del json, headers
            raise httpx.ReadTimeout("timed out", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", _TimeoutClient)
    client = LLMClient(endpoint="http://localhost:8000", model="qwen25-7b", timeout_seconds=1)

    with pytest.raises(ForgeError) as exc:
        client.chat_json_with_trace(system_prompt="sys", user_prompt="usr", response_format=True)

    assert exc.value.message == "LLM request timed out"
    assert exc.value.status_code == 504
    assert exc.value.details["timeout_seconds"] == 1


def test_llm_client_normalizes_endpoint_with_leading_equals() -> None:
    client = LLMClient(endpoint="==http://localhost:8000", model="qwen25-7b", timeout_seconds=1)
    assert client._chat_url() == "http://localhost:8000/v1/chat/completions"


def test_chat_json_with_trace_uses_max_completion_tokens_for_gpt5(monkeypatch) -> None:
    captured = {}

    class _CaptureClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = dict(json or {})
            captured["headers"] = headers

            class _Resp:
                status_code = 200
                text = '{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'

                @staticmethod
                def json():
                    return {"choices": [{"message": {"content": '{"ok":true}'}}]}

            return _Resp()

    monkeypatch.setattr(httpx, "Client", _CaptureClient)
    client = LLMClient(endpoint="https://api.openai.com/v1/chat/completions", model="gpt-5", timeout_seconds=5)
    out = client.chat_json_with_trace(system_prompt="sys", user_prompt="usr", response_format=True, max_tokens=123)
    assert out.get("parsed") == {"ok": True}
    sent = dict(captured.get("json") or {})
    assert "max_completion_tokens" in sent
    assert sent.get("max_completion_tokens") == 123
    assert "max_tokens" not in sent
    assert "temperature" not in sent


def test_fallback_chat_endpoint_uses_messages_not_prompt() -> None:
    captured = {}

    class _FallbackClient:
        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = dict(json or {})
            captured["headers"] = headers

            class _Resp:
                status_code = 400
                text = '{"error":{"message":"bad"}}'

                @staticmethod
                def json():
                    return {"error": {"message": "bad"}}

            return _Resp()

    client = LLMClient(endpoint="https://api.openai.com/v1/chat/completions", model="gpt-5", timeout_seconds=5)
    trace = client._fallback_simple_with_trace(  # noqa: SLF001
        client=_FallbackClient(),
        system_prompt="sys",
        user_prompt="usr",
        max_tokens=77,
        response_format=True,
    )
    assert trace.get("error") == "http_status:400"
    sent = dict(captured.get("json") or {})
    assert "messages" in sent
    assert "prompt" not in sent
    assert sent.get("max_completion_tokens") == 77
    assert "temperature" not in sent


def test_chat_json_with_trace_sets_temperature_zero_for_non_gpt5(monkeypatch) -> None:
    captured = {}

    class _CaptureClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = dict(json or {})
            captured["headers"] = headers

            class _Resp:
                status_code = 200
                text = '{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'

                @staticmethod
                def json():
                    return {"choices": [{"message": {"content": '{"ok":true}'}}]}

            return _Resp()

    monkeypatch.setattr(httpx, "Client", _CaptureClient)
    client = LLMClient(endpoint="http://localhost:8000/v1/chat/completions", model="qwen25-7b", timeout_seconds=5)
    out = client.chat_json_with_trace(system_prompt="sys", user_prompt="usr", response_format=True, max_tokens=123)
    assert out.get("parsed") == {"ok": True}
    sent = dict(captured.get("json") or {})
    assert sent.get("temperature") == 0


def test_chat_json_with_trace_accepts_json_schema_response_format(monkeypatch) -> None:
    captured = {}

    class _CaptureClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = dict(json or {})
            captured["headers"] = headers

            class _Resp:
                status_code = 200
                text = '{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'

                @staticmethod
                def json():
                    return {"choices": [{"message": {"content": '{"ok":true}'}}]}

            return _Resp()

    monkeypatch.setattr(httpx, "Client", _CaptureClient)
    client = LLMClient(endpoint="http://localhost:8000/v1/chat/completions", model="qwen25-7b", timeout_seconds=5)
    schema_format = {"type": "json_schema", "json_schema": {"name": "x", "strict": True, "schema": {"type": "object"}}}
    out = client.chat_json_with_trace(
        system_prompt="sys",
        user_prompt="usr",
        response_format=schema_format,
        max_tokens=123,
    )
    assert out.get("parsed") == {"ok": True}
    sent = dict(captured.get("json") or {})
    assert sent.get("response_format") == schema_format

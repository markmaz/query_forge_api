from __future__ import annotations

import json

import pytest

from app.exceptions.service_error import ServiceError
from app.services.chat.forge_insights_router_service import ForgeInsightsRouterService


class _FakeChat:
    def __init__(self) -> None:
        self.calls = []

    def chat(self, body, *, workspace_id, user_id):
        self.calls.append((body, workspace_id, user_id))
        return {
            "id": "chatcmpl_1",
            "conversation_id": "fi_1",
            "message": {"role": "assistant", "content": "chat"},
            "debug": None,
        }


class _FakePlanner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def plan(self, payload, *, user_id):
        self.calls.append((payload, user_id))
        return self.result


class _FakeExecution:
    def __init__(self):
        self.calls = []

    def start(self, workspace_id, payload, query_args):
        self.calls.append((workspace_id, payload, query_args))
        return {"jobId": "job-1", "statementId": "stmt-1"}, 200


class _FakeLLM:
    def __init__(self, out=None, exc: Exception | None = None):
        self._out = out or {"route": "chat", "confidence": 1.0, "reason": "chat"}
        self._exc = exc
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(dict(kwargs))
        del kwargs
        if self._exc is not None:
            raise self._exc
        return self._out


class _FakeFewshots:
    def __init__(self, examples=None):
        self.examples = list(examples or [])
        self.calls = []

    def get_examples(self, *, workspace_id: str, user_id: str):
        self.calls.append((workspace_id, user_id))
        return list(self.examples)


class _FakeDomainVector:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def search_domains(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"results": list(self.results)}


def _body(prompt: str, *, conversation_id: str = "fi_1", debug: bool = False):
    return {
        "conversation_id": conversation_id,
        "messages": [{"role": "user", "content": prompt}],
        "debug": debug,
    }


def test_router_chat_path_calls_chat_service() -> None:
    chat = _FakeChat()
    planner = _FakePlanner(result={})
    execution = _FakeExecution()
    llm = _FakeLLM(out={"route": "chat", "confidence": 0.95, "reason": "general chat"})
    fewshots = _FakeFewshots(["Show me students by school"])
    svc = ForgeInsightsRouterService(
        chat_service=chat,
        planner_domain_service=planner,
        execution_service=execution,
        llm_client=llm,
        fewshot_service=fewshots,
        route_domain_vector_enabled=False,
    )

    out, status = svc.ask(_body("Hello there", debug=True), workspace_id="ws-1", user_id="u1", query_args={})
    assert status == 200
    assert out["mode"] == "chat"
    assert out["route"] == "chat"
    assert len(chat.calls) == 1
    assert planner.calls == []
    assert execution.calls == []
    assert out["debug"]["route_decision"]["route"] == "chat"
    assert len(llm.calls) == 1
    assert "Examples that should route to education_pipeline" in llm.calls[0]["user_prompt"]
    assert fewshots.calls == [("ws-1", "u1")]


def test_router_education_path_runs_planner_and_execution() -> None:
    chat = _FakeChat()
    planner = _FakePlanner(
        result={
            "conversation_id": "fi_1",
            "trace_id": "trace-1",
            "sql_json": {"domainId": 5},
            "explanation": {"summary": "I ran an education query."},
            "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
        }
    )
    execution = _FakeExecution()
    llm = _FakeLLM(out={"route": "education_pipeline", "confidence": 0.99, "reason": "education analytics"})
    svc = ForgeInsightsRouterService(
        chat_service=chat,
        planner_domain_service=planner,
        execution_service=execution,
        llm_client=llm,
        fewshot_service=_FakeFewshots(["Show me students by school"]),
        route_domain_vector_enabled=False,
    )

    out, status = svc.ask(_body("Show me students by school"), workspace_id="ws-1", user_id="u1", query_args={"mode": "preview"})
    assert status == 200
    assert out["mode"] == "education_pipeline"
    assert out["route"] == "plan_domain"
    assert out["execution"]["jobId"] == "job-1"
    assert out["message"]["content"] == "I ran an education query."
    assert len(planner.calls) == 1
    planner_payload, planner_user = planner.calls[0]
    assert planner_payload["allow_unknown_conversation"] is True
    assert planner_user == "u1"
    assert len(execution.calls) == 1
    ws, execution_payload, qargs = execution.calls[0]
    assert ws == "ws-1"
    assert execution_payload["sqlJson"] == {"domainId": 5}
    assert qargs == {"mode": "preview"}
    assert chat.calls == []


def test_router_education_path_requires_sql_json() -> None:
    svc = ForgeInsightsRouterService(
        chat_service=_FakeChat(),
        planner_domain_service=_FakePlanner(result={"validation": {"is_valid": False}}),
        execution_service=_FakeExecution(),
        llm_client=_FakeLLM(out={"route": "education_pipeline", "confidence": 0.99, "reason": "education analytics"}),
        fewshot_service=_FakeFewshots(),
        route_domain_vector_enabled=False,
    )
    with pytest.raises(ServiceError) as exc:
        svc.ask(_body("students by school"), workspace_id="ws-1", user_id="u1", query_args={})
    assert exc.value.status_code == 422


def test_router_falls_back_to_heuristic_when_llm_fails() -> None:
    planner = _FakePlanner(
        result={
            "conversation_id": "fi_1",
            "trace_id": "trace-1",
            "sql_json": {"domainId": 5},
            "explanation": {"summary": "fallback"},
            "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
        }
    )
    execution = _FakeExecution()
    svc = ForgeInsightsRouterService(
        chat_service=_FakeChat(),
        planner_domain_service=planner,
        execution_service=execution,
        llm_client=_FakeLLM(exc=ServiceError("llm down", status_code=502)),
        fewshot_service=_FakeFewshots(["Count students by school"]),
        route_domain_vector_enabled=False,
    )
    out, status = svc.ask(_body("Show me student attendance by school"), workspace_id="ws-1", user_id="u1", query_args={})
    assert status == 200
    assert out["mode"] == "education_pipeline"
    assert out["route_decision"]["method"] == "heuristic"


def test_router_hard_education_rule_overrides_llm_chat_decision() -> None:
    planner = _FakePlanner(
        result={
            "conversation_id": "fi_1",
            "trace_id": "trace-1",
            "sql_json": {"domainId": 5},
            "explanation": {"summary": "education path"},
            "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
        }
    )
    execution = _FakeExecution()
    # Even if classifier says chat, the hard education rule should route to pipeline.
    svc = ForgeInsightsRouterService(
        chat_service=_FakeChat(),
        planner_domain_service=planner,
        execution_service=execution,
        llm_client=_FakeLLM(out={"route": "chat", "confidence": 0.99, "reason": "general"}),
        fewshot_service=_FakeFewshots(),
        route_domain_vector_enabled=False,
    )

    out, status = svc.ask(
        _body("Show me all the students enrolled at Barksdale Elementary"),
        workspace_id="ws-1",
        user_id="u1",
        query_args={},
    )
    assert status == 200
    assert out["mode"] == "education_pipeline"
    assert out["route_decision"]["route"] == "education_pipeline"
    assert out["route_decision"]["hard_match"] is True


def test_router_hard_education_rule_overrides_llm_chat_for_staff_at_school_prompt() -> None:
    planner = _FakePlanner(
        result={
            "conversation_id": "fi_1",
            "trace_id": "trace-1",
            "sql_json": {"domainId": 5},
            "explanation": {"summary": "education path"},
            "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
        }
    )
    execution = _FakeExecution()
    svc = ForgeInsightsRouterService(
        chat_service=_FakeChat(),
        planner_domain_service=planner,
        execution_service=execution,
        llm_client=_FakeLLM(out={"route": "chat", "confidence": 0.99, "reason": "general"}),
        fewshot_service=_FakeFewshots(),
        route_domain_vector_enabled=False,
    )

    out, status = svc.ask(
        _body("Show me the staff at Barksdale Elementary"),
        workspace_id="ws-1",
        user_id="u1",
        query_args={},
    )
    assert status == 200
    assert out["mode"] == "education_pipeline"
    assert out["route_decision"]["route"] == "education_pipeline"
    assert out["route_decision"]["hard_match"] is True


def test_router_invalid_request_returns_json_safe_validation_details() -> None:
    svc = ForgeInsightsRouterService(
        chat_service=_FakeChat(),
        planner_domain_service=_FakePlanner(result={}),
        execution_service=_FakeExecution(),
        llm_client=_FakeLLM(),
        fewshot_service=_FakeFewshots(),
        route_domain_vector_enabled=False,
    )
    with pytest.raises(ServiceError) as exc:
        svc.ask({"messages": []}, workspace_id="ws-1", user_id="u1", query_args={})
    assert exc.value.status_code == 400
    details = exc.value.details or {}
    errors = details.get("errors") or []
    assert isinstance(errors, list)
    if errors:
        ctx = errors[0].get("ctx")
        if ctx is not None:
            assert isinstance(ctx, dict)
            assert all(isinstance(v, str) for v in ctx.values())
    json.dumps(exc.value.to_dict())


def test_router_trims_oversized_inbound_messages_instead_of_400() -> None:
    chat = _FakeChat()
    svc = ForgeInsightsRouterService(
        chat_service=chat,
        planner_domain_service=_FakePlanner(result={}),
        execution_service=_FakeExecution(),
        llm_client=_FakeLLM(out={"route": "chat", "confidence": 0.95, "reason": "chat"}),
        fewshot_service=_FakeFewshots(),
        route_domain_vector_enabled=False,
    )
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(35)]
    messages[-1] = {"role": "user", "content": "hello there"}

    out, status = svc.ask(
        {
            "conversation_id": "fi_1",
            "messages": messages,
            "debug": True,
        },
        workspace_id="ws-1",
        user_id="u1",
        query_args={},
    )

    assert status == 200
    assert out["mode"] == "chat"
    assert len(chat.calls) == 1
    forwarded_body = chat.calls[0][0]
    assert len(forwarded_body["messages"]) == 30
    assert forwarded_body["messages"][-1]["content"] == "hello there"
    assert out["debug"]["route_decision"]["inbound_messages_truncated"] is True


def test_router_keyword_force_rule_routes_to_education_pipeline() -> None:
    planner = _FakePlanner(
        result={
            "conversation_id": "fi_1",
            "trace_id": "trace-1",
            "sql_json": {"domainId": 5},
            "explanation": {"summary": "education path"},
            "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
        }
    )
    execution = _FakeExecution()
    svc = ForgeInsightsRouterService(
        chat_service=_FakeChat(),
        planner_domain_service=planner,
        execution_service=execution,
        llm_client=_FakeLLM(out={"route": "chat", "confidence": 0.99, "reason": "general"}),
        fewshot_service=_FakeFewshots(),
        route_domain_vector_enabled=False,
    )
    out, status = svc.ask(
        _body("Show discipline by grade level"),
        workspace_id="ws-1",
        user_id="u1",
        query_args={},
    )
    assert status == 200
    assert out["mode"] == "education_pipeline"
    assert out["route_decision"]["keyword_force_match"] is True
    assert out["route_decision"]["hard_match"] is True


def test_router_domain_vector_match_routes_to_education_pipeline() -> None:
    planner = _FakePlanner(
        result={
            "conversation_id": "fi_1",
            "trace_id": "trace-1",
            "sql_json": {"domainId": 5},
            "explanation": {"summary": "education path"},
            "validation": {"is_valid": True, "errors": [], "repairs_applied": []},
        }
    )
    execution = _FakeExecution()
    vector = _FakeDomainVector(results=[{"domain_id": 5, "score": 0.78}])
    svc = ForgeInsightsRouterService(
        chat_service=_FakeChat(),
        planner_domain_service=planner,
        execution_service=execution,
        llm_client=_FakeLLM(out={"route": "chat", "confidence": 0.99, "reason": "general"}),
        fewshot_service=_FakeFewshots(),
        domain_vector_service=vector,
        route_domain_vector_enabled=True,
    )
    out, status = svc.ask(
        _body("Montgomery County snapshot"),
        workspace_id="ws-1",
        user_id="u1",
        query_args={},
    )
    assert status == 200
    assert out["mode"] == "education_pipeline"
    assert out["route_decision"]["method"] == "domain_vector"
    assert out["route_decision"]["domain_vector_match"]["matched"] is True
    assert len(vector.calls) == 1

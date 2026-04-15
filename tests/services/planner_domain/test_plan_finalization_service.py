import pytest
from valkey.exceptions import ValkeyError

from app.services.planner_domain.plan_finalization_service import PlanFinalizationService


class _FakeConversationStore:
    def __init__(self):
        self.calls = []

    def save_state(self, **kwargs):
        self.calls.append(kwargs)


class _FakePipelineTrace:
    def __init__(self):
        self.profile_calls = []
        self.trace_calls = []

    def emit_profile_log(self, **kwargs):
        self.profile_calls.append(kwargs)

    def emit_trace_log(self, **kwargs):
        self.trace_calls.append(kwargs)

    def trace_log_path(self):
        return "/tmp/plan_trace.jsonl"


def test_plan_finalization_service_persists_state_and_sets_trace_metadata():
    store = _FakeConversationStore()
    trace = _FakePipelineTrace()
    svc = PlanFinalizationService(
        conversation_store=store,
        conversation_ttl_seconds=600,
        pipeline_trace_service=trace,
    )
    response = {"technical_details": {}}
    out = svc.finalize(
        workspace_id="ws-1",
        user_id="user-1",
        normalized_prompt="show students",
        trace_id="trace-1",
        conversation_id="conv-1",
        plan_json_v2={"base_domain_id": 6},
        sql_json={"version": 1},
        profile_steps=[{"step": "x"}],
        profile_enabled=True,
        trace_capture_enabled=True,
        pipeline_trace={"steps": []},
        timings={},
        started_at=0.0,
        fast_mode=False,
        planner_unified_llm=False,
        planner_compact_enabled=True,
        response=response,
    )
    assert store.calls
    assert trace.profile_calls
    assert trace.trace_calls
    assert out["technical_details"]["pipeline_trace_enabled"] is True
    assert out["technical_details"]["pipeline_trace_log_file"] == "/tmp/plan_trace.jsonl"
    assert trace.profile_calls[0]["total_ms"] >= 0


def test_plan_finalization_service_tolerates_conversation_store_backend_failures():
    class _FailingConversationStore:
        def save_state(self, **kwargs):
            del kwargs
            raise ValkeyError("valkey unavailable")

    trace = _FakePipelineTrace()
    svc = PlanFinalizationService(
        conversation_store=_FailingConversationStore(),
        conversation_ttl_seconds=600,
        pipeline_trace_service=trace,
    )

    out = svc.finalize(
        workspace_id="ws-1",
        user_id="user-1",
        normalized_prompt="show students",
        trace_id="trace-1",
        conversation_id="conv-1",
        plan_json_v2={"base_domain_id": 6},
        sql_json={"version": 1},
        profile_steps=[{"step": "x"}],
        profile_enabled=True,
        trace_capture_enabled=True,
        pipeline_trace={"steps": []},
        timings={},
        started_at=0.0,
        fast_mode=False,
        planner_unified_llm=False,
        planner_compact_enabled=True,
        response={"technical_details": {}},
    )

    assert trace.profile_calls
    assert trace.trace_calls
    assert out["technical_details"]["pipeline_trace_enabled"] is True


def test_plan_finalization_service_surfaces_unexpected_conversation_store_errors():
    class _FailingConversationStore:
        def save_state(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected store failure")

    svc = PlanFinalizationService(
        conversation_store=_FailingConversationStore(),
        conversation_ttl_seconds=600,
        pipeline_trace_service=_FakePipelineTrace(),
    )

    with pytest.raises(AssertionError, match="unexpected store failure"):
        svc.finalize(
            workspace_id="ws-1",
            user_id="user-1",
            normalized_prompt="show students",
            trace_id="trace-1",
            conversation_id="conv-1",
            plan_json_v2={"base_domain_id": 6},
            sql_json={"version": 1},
            profile_steps=[{"step": "x"}],
            profile_enabled=True,
            trace_capture_enabled=True,
            pipeline_trace={"steps": []},
            timings={},
            started_at=0.0,
            fast_mode=False,
            planner_unified_llm=False,
            planner_compact_enabled=True,
            response={"technical_details": {}},
        )

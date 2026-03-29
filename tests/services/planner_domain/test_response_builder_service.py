from app.services.planner_domain.response_builder_service import PlannerResponseBuilderService


class _Validated:
    def __init__(self):
        self.plan_json = {"base_domain_id": 6}
        self.is_valid = True
        self.issues = []
        self.repairs_applied = []


def test_build_plan_response_includes_clarification_and_trace_metadata():
    svc = PlannerResponseBuilderService()
    out = svc.build_plan_response(
        validated=_Validated(),
        sql_json={"version": 1},
        explanation={"summary": "Summary"},
        next_actions=[],
        next_actions_status="ready",
        trace_id="trace-1",
        conversation_id="conv-1",
        fast_mode=False,
        planner_unified_llm=True,
        planner_compact_enabled=True,
        llm_resolution={"model": "gpt"},
        timings={"total": 12},
        unified_trace={"needs_clarification": True},
        clarification_question="Which school?",
        planner_confidence=0.42,
        pipeline_profile=[{"step": "x"}],
        pipeline_trace_enabled=True,
        pipeline_trace_log_file="/tmp/trace.jsonl",
        debug_payload={"foo": "bar"},
    )
    assert out["needs_clarification"] is True
    assert out["clarification_question"] == "Which school?"
    assert out["planner_confidence"] == 0.42
    assert out["pipeline_profile"] == [{"step": "x"}]
    assert out["debug"] == {"foo": "bar"}
    assert out["technical_details"]["pipeline_trace_enabled"] is True
    assert out["technical_details"]["pipeline_trace_log_file"] == "/tmp/trace.jsonl"


def test_build_debug_payload_adds_optional_pipeline_sections():
    svc = PlannerResponseBuilderService()
    out = svc.build_debug_payload(
        normalized_prompt="show students",
        conversation_id="conv-1",
        conversation_context_used=True,
        followup_mode=False,
        conversation_seeded_from_client=False,
        selected_domain_id=6,
        capabilities={"domain_id": 6},
        capabilities_llm={"domain_id": 6},
        domain_candidates=[{"domain_id": 6}],
        domain_ranking=[{"domain_id": 6}],
        rerank_signals=["student_listing"],
        column_shortlist_count=2,
        slot_hints={"intent": "list"},
        semantic_assist_enabled=True,
        semantic_value_alias_constraints=[],
        semantic_value_alias_normalization={"rewrites": []},
        semantic_grounding={"candidates": []},
        semester_indicator_columns={"spring": "wt1.is_spring"},
        slot_raw_json="{}",
        slot_attempts=1,
        slot_repaired=False,
        country_value_normalization=[],
        school_year_value_normalization=[],
        semester_value_normalization=[],
        school_name_filter_normalization=[],
        staff_role_filter_normalization=[],
        adm_filter_normalization=[],
        district_county_retry_hint="",
        llm_raw_json="{}",
        llm_attempts=1,
        llm_repaired=False,
        planner_unified_llm=False,
        unified_llm_trace={},
        explanation_summary_trace=None,
        next_actions_trace=None,
        technical_details={"trace_id": "trace-1"},
        profile_enabled=True,
        pipeline_profile=[{"step": "a"}],
        trace_capture_enabled=True,
        pipeline_trace={"steps": [{"step": "x"}]},
    )
    assert out["pipeline_profile"] == [{"step": "a"}]
    assert out["pipeline_trace"]["steps"][0]["step"] == "x"

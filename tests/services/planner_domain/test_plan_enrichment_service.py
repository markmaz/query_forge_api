from app.services.planner_domain.plan_enrichment_service import PlanEnrichmentService


class _FakeExplanation:
    def build_explanation(self, **kwargs):
        del kwargs
        return {"summary": "Base summary", "domain": {}}

    def maybe_polish_summary(self, *, prompt, explanation):
        del prompt
        explanation = dict(explanation)
        explanation["summary"] = "Polished summary"
        return explanation, {"used": True}


class _FakeNextActions:
    def maybe_generate(self, **kwargs):
        del kwargs
        return [{"title": "Next"}], {"used": True}


def test_plan_enrichment_service_defers_next_actions_when_async():
    svc = PlanEnrichmentService(
        explanation_service=_FakeExplanation(),
        next_actions_service=_FakeNextActions(),
    )
    out = svc.run(
        selected_domain_id=6,
        selected_domain_name="Students",
        validated_plan_json={"domain_name": "Students"},
        capabilities={},
        domain_candidates=[],
        ranking_debug=[],
        shortlisted_columns=[],
        country_debug=[],
        school_year_debug=[],
        semester_debug=[],
        prompt="show students",
        next_actions_async=True,
        profile_steps=[],
        profile_enabled=False,
        pipeline_trace={"steps": []},
        trace_capture_enabled=False,
    )
    assert out.explanation["summary"] == "Polished summary"
    assert out.next_actions == []
    assert out.next_actions_status == "deferred"
    assert out.next_actions_trace["deferred"] is True


def test_plan_enrichment_service_generates_next_actions_when_sync():
    svc = PlanEnrichmentService(
        explanation_service=_FakeExplanation(),
        next_actions_service=_FakeNextActions(),
    )
    out = svc.run(
        selected_domain_id=6,
        selected_domain_name="Students",
        validated_plan_json={"domain_name": "Students"},
        capabilities={},
        domain_candidates=[],
        ranking_debug=[],
        shortlisted_columns=[],
        country_debug=[],
        school_year_debug=[],
        semester_debug=[],
        prompt="show students",
        next_actions_async=False,
        profile_steps=[],
        profile_enabled=False,
        pipeline_trace={"steps": []},
        trace_capture_enabled=False,
    )
    assert out.next_actions == [{"title": "Next"}]
    assert out.next_actions_status == "ready"

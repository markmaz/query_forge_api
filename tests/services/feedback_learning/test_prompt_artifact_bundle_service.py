from __future__ import annotations

from app.exceptions.forge_error import ForgeError
from app.schemas.feedback_learning import PromptArtifactBundle
from app.services.feedback_learning.prompt_artifact_bundle_service import PromptArtifactBundleService


class _FakePromptFeedbackRepository:
    def __init__(self, row):
        self._row = row
        self.calls = []

    def get_feedback(self, prompt_feedback_id: int):
        self.calls.append(prompt_feedback_id)
        return self._row


class _FakePipelineTraceService:
    def __init__(self, profile):
        self._profile = profile
        self.calls = []

    def get_pipeline_profile(self, *, trace_id: str, workspace_id: str, user_id: str):
        self.calls.append({"trace_id": trace_id, "workspace_id": workspace_id, "user_id": user_id})
        if self._profile == "missing":
            raise ForgeError("Pipeline profile not found", status_code=404)
        return self._profile


class _FakeConversationStore:
    def __init__(self, state):
        self._state = state
        self.calls = []

    def get_state(self, *, workspace_id: str, user_id: str, conversation_id: str):
        self.calls.append(
            {"workspace_id": workspace_id, "user_id": user_id, "conversation_id": conversation_id}
        )
        return self._state


def test_build_bundle_uses_feedback_row_trace_and_conversation_state() -> None:
    repository = _FakePromptFeedbackRepository(
        {
            "id": 18,
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "trace_id": "trace-18",
            "prompt_text": "Show me days off",
            "normalized_prompt": None,
            "response_json": {
                "trace_id": "trace-18",
                "conversation_id": "pdc_18",
                "plan_json_v2": {"base_domain_id": 6, "intent": "calendar_lookup"},
                "debug": {"domain_candidates": [{"domain_id": 6, "score": 0.92}]},
                "explanation": {"summary": "calendar domain"},
            },
            "meta_json": {"domain_id": 6},
        }
    )
    pipeline_trace_service = _FakePipelineTraceService(
        {
            "trace_id": "trace-18",
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "conversation_id": "pdc_18",
            "prompt": "Show me days off",
            "pipeline_trace": {
                "normalized_prompt": "show me days off",
                "steps": [
                    {
                        "step": "map_to_sqljson",
                        "data": {"sql_json": {"version": 1, "domainId": 6}},
                    }
                ],
            },
        }
    )
    conversation_store = _FakeConversationStore(
        {
            "last_prompt": "Show me days off",
            "trace_id": "trace-18",
            "plan_json_v2": {"base_domain_id": 6, "intent": "calendar_lookup"},
            "sql_json": {"version": 1, "domainId": 6},
        }
    )

    service = PromptArtifactBundleService(
        prompt_feedback_repository=repository,
        pipeline_trace_service=pipeline_trace_service,
        conversation_store=conversation_store,
    )
    bundle = service.build_bundle(18)

    assert isinstance(bundle, PromptArtifactBundle)
    assert bundle.prompt == "Show me days off"
    assert bundle.normalized_prompt == "show me days off"
    assert bundle.generated_sql == {"version": 1, "domainId": 6}
    assert bundle.planner_input["conversation_id"] == "pdc_18"
    assert bundle.candidate_domains == [{"domain_id": 6, "score": 0.92}]


def test_build_bundle_raises_when_required_artifacts_missing() -> None:
    repository = _FakePromptFeedbackRepository(
        {
            "id": 19,
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "trace_id": None,
            "prompt_text": None,
            "normalized_prompt": None,
            "response_json": {},
            "meta_json": {},
        }
    )

    service = PromptArtifactBundleService(
        prompt_feedback_repository=repository,
        pipeline_trace_service=_FakePipelineTraceService("missing"),
        conversation_store=_FakeConversationStore(None),
    )

    try:
        service.build_bundle(19)
        assert False, "expected missing artifact failure"
    except ForgeError as exc:
        assert exc.status_code == 422
        assert exc.details["missing_fields"] == [
            "prompt",
            "normalized_prompt",
            "planner_output",
            "generated_sql",
            "output_json",
        ]


def test_build_bundle_skips_missing_pipeline_profile() -> None:
    repository = _FakePromptFeedbackRepository(
        {
            "id": 20,
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "trace_id": "trace-20",
            "prompt_text": "Show schools",
            "normalized_prompt": "show schools",
            "response_json": {
                "trace_id": "trace-20",
                "sql_json": {"version": 1, "domainId": 3},
                "plan_json_v2": {"base_domain_id": 3},
            },
            "meta_json": {},
        }
    )
    service = PromptArtifactBundleService(
        prompt_feedback_repository=repository,
        pipeline_trace_service=_FakePipelineTraceService("missing"),
        conversation_store=_FakeConversationStore(None),
    )

    bundle = service.build_bundle(20)

    assert bundle.trace_id == "trace-20"
    assert bundle.generated_sql == {"version": 1, "domainId": 3}

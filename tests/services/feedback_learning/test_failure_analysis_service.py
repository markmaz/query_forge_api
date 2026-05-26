from __future__ import annotations

from app.exceptions.forge_error import ForgeError
from app.schemas.feedback_learning import EvaluatorAnalysis, GovernanceDecision, NormalizedCandidate, PromptArtifactBundle, ProposedChange, RootCause
from app.services.feedback_learning.failure_analysis_service import FailureAnalysisService
from app.services.feedback_learning.evaluator_client import EvaluatorClientResult


def _bundle() -> PromptArtifactBundle:
    return PromptArtifactBundle.model_validate(
        {
            "prompt_feedback_id": 41,
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "trace_id": "trace-41",
            "conversation_id": "pdc_41",
            "prompt": "Show attendance exceptions",
            "normalized_prompt": "show attendance exceptions",
            "planner_input": {
                "workspace_id": "ws-1",
                "trace_id": "trace-41",
                "conversation_id": "pdc_41",
                "prompt": "Show attendance exceptions",
                "normalized_prompt": "show attendance exceptions",
                "meta": {},
            },
            "planner_output": {"trace_id": "trace-41", "plan_json_v2": {"base_domain_id": 6}},
            "generated_sql": {"version": 1, "domainId": 6},
            "output_json": {"trace_id": "trace-41"},
        }
    )


class _PromptFeedbackRepository:
    def __init__(self, exists=True):
        self.exists = exists
        self.calls = []

    def feedback_exists(self, *, prompt_feedback_id: int) -> bool:
        self.calls.append(prompt_feedback_id)
        return self.exists


class _PromptFailureAnalysisRepository:
    def __init__(self, existing=None, create_id=55):
        self.existing = existing
        self.create_id = create_id
        self.get_calls = []
        self.create_calls = []
        self.completed_calls = []
        self.failed_calls = []

    def get_by_feedback_id(self, *, prompt_feedback_id: int):
        self.get_calls.append(prompt_feedback_id)
        return self.existing

    def create_pending(self, *, prompt_feedback_id: int, evaluator_model=None, evaluator_version=None):
        self.create_calls.append(
            {
                "prompt_feedback_id": prompt_feedback_id,
                "evaluator_model": evaluator_model,
                "evaluator_version": evaluator_version,
            }
        )
        return self.create_id

    def mark_completed(self, *, analysis_id: int, failure_verdict, confidence, analysis_json, raw_llm_output):
        self.completed_calls.append(
            {
                "analysis_id": analysis_id,
                "failure_verdict": failure_verdict,
                "confidence": confidence,
                "analysis_json": analysis_json,
                "raw_llm_output": raw_llm_output,
            }
        )
        return 1

    def mark_failed(self, *, analysis_id: int, error_message: str, raw_llm_output=None):
        self.failed_calls.append(
            {
                "analysis_id": analysis_id,
                "error_message": error_message,
                "raw_llm_output": raw_llm_output,
            }
        )
        return 1


class _BundleService:
    def __init__(self, bundle=None, error=None):
        self.bundle = bundle or _bundle()
        self.error = error
        self.calls = []

    def build_bundle(self, prompt_feedback_id: int):
        self.calls.append(prompt_feedback_id)
        if self.error is not None:
            raise self.error
        return self.bundle


class _EvaluatorClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self._model = "gpt-4.1-mini"

    def analyze_failure_with_trace(self, bundle):
        self.calls.append(bundle)
        if self.error is not None:
            raise self.error
        return self.result


class _CandidateNormalizer:
    def __init__(self, normalized):
        self.normalized = normalized
        self.calls = []

    def normalize(self, *, failure_analysis_id: int, workspace_id: str, proposed_change: ProposedChange):
        self.calls.append(
            {
                "failure_analysis_id": failure_analysis_id,
                "workspace_id": workspace_id,
                "proposed_change": proposed_change,
            }
        )
        return self.normalized


class _CandidateWriterService:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def upsert_candidate(self, candidate):
        self.calls.append(candidate)
        return dict(self.row)


class _GovernorService:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def evaluate_candidate(self, candidate):
        self.calls.append(candidate)
        return self.decision


class _CandidateRepository:
    def __init__(self):
        self.calls = []

    def update_review(self, *, candidate_id: int, governance_status: str, reviewed_by=None, reviewed_at=None, auto_apply_eligible=None):
        self.calls.append(
            {
                "candidate_id": candidate_id,
                "governance_status": governance_status,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "auto_apply_eligible": auto_apply_eligible,
            }
        )
        return 1


def _analysis(*, verdict: str = "domain_error", proposed_changes=None) -> EvaluatorAnalysis:
    return EvaluatorAnalysis.model_validate(
        {
            "verdict": verdict,
            "failure_modes": ["missing_alias"] if verdict != "inconclusive" else [],
            "root_causes": [] if verdict == "inconclusive" else [RootCause(type="semantic_gap", target="student_name", evidence="missing alias")],
            "proposed_changes": proposed_changes or [],
            "confidence": 0.91,
        }
    )


def _normalized_candidate() -> NormalizedCandidate:
    return NormalizedCandidate.model_validate(
        {
            "failure_analysis_id": 55,
            "target_type": "semantic_override",
            "concept_key": "student_name",
            "domain_key": None,
            "change_type": "add_alias",
            "payload_json": {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
            "payload_hash": "hash-55",
            "risk_level": "low",
            "evidence_count": 1,
            "confidence": 0.91,
            "governance_status": "pending",
            "auto_apply_eligible": False,
            "source_scope": "workspace",
            "workspace_id": "ws-1",
            "workspace_scope_key": "workspace:ws-1",
        }
    )


def test_failure_analysis_service_happy_path_generates_candidate_and_updates_governance() -> None:
    proposed_change = ProposedChange.model_validate(
        {
            "target_type": "semantic_override",
            "target_key": "student_name",
            "change_type": "add_alias",
            "payload": {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
            "risk_level": "low",
            "confidence": 0.91,
        }
    )
    analysis_repository = _PromptFailureAnalysisRepository()
    candidate_repository = _CandidateRepository()
    service = FailureAnalysisService(
        prompt_feedback_repository=_PromptFeedbackRepository(),
        analysis_repository=analysis_repository,
        prompt_artifact_bundle_service=_BundleService(),
        evaluator_client=_EvaluatorClient(
            EvaluatorClientResult(
                analysis=_analysis(proposed_changes=[proposed_change]),
                raw_output='{"verdict":"domain_error"}',
                attempts=1,
                model="gpt-4.1-mini",
                trace={"provider": "test"},
            )
        ),
        candidate_normalizer=_CandidateNormalizer(_normalized_candidate()),
        candidate_writer_service=_CandidateWriterService({"id": 88, "payload_hash": "hash-55"}),
        governor_service=_GovernorService(
            GovernanceDecision.model_validate(
                {
                    "governance_status": "pending",
                    "auto_apply_eligible": True,
                    "reason_code": "AUTO_APPLY_ELIGIBLE",
                }
            )
        ),
        candidate_repository=candidate_repository,
    )

    result = service.analyze_feedback(41)

    assert result.analysis_id == 55
    assert result.status == "completed"
    assert result.candidate_count == 1
    assert analysis_repository.completed_calls[0]["failure_verdict"] == "domain_error"
    assert candidate_repository.calls == [
        {
            "candidate_id": 88,
            "governance_status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "auto_apply_eligible": True,
        }
    ]


def test_failure_analysis_service_is_idempotent_for_completed_rows() -> None:
    existing = {
        "id": 90,
        "prompt_feedback_id": 41,
        "status": "completed",
        "failure_verdict": "domain_error",
        "confidence": 0.91,
        "analysis_json": {"verdict": "domain_error"},
    }
    bundle_service = _BundleService()
    service = FailureAnalysisService(
        prompt_feedback_repository=_PromptFeedbackRepository(),
        analysis_repository=_PromptFailureAnalysisRepository(existing=existing),
        prompt_artifact_bundle_service=bundle_service,
        evaluator_client=_EvaluatorClient(result=None),
        candidate_normalizer=_CandidateNormalizer(_normalized_candidate()),
        candidate_writer_service=_CandidateWriterService({"id": 88}),
        governor_service=_GovernorService(
            GovernanceDecision.model_validate(
                {
                    "governance_status": "pending",
                    "auto_apply_eligible": False,
                    "reason_code": "AUTO_APPLY_ELIGIBLE",
                }
            )
        ),
        candidate_repository=_CandidateRepository(),
    )

    result = service.analyze_feedback(41)

    assert result.analysis_id == 90
    assert result.status == "completed"
    assert bundle_service.calls == []


def test_failure_analysis_service_stops_on_inconclusive_without_candidates() -> None:
    analysis_repository = _PromptFailureAnalysisRepository()
    candidate_repository = _CandidateRepository()
    normalizer = _CandidateNormalizer(_normalized_candidate())
    service = FailureAnalysisService(
        prompt_feedback_repository=_PromptFeedbackRepository(),
        analysis_repository=analysis_repository,
        prompt_artifact_bundle_service=_BundleService(),
        evaluator_client=_EvaluatorClient(
            EvaluatorClientResult(
                analysis=_analysis(verdict="inconclusive", proposed_changes=[]),
                raw_output='{"verdict":"inconclusive"}',
                attempts=1,
                model="gpt-4.1-mini",
                trace={"provider": "test"},
            )
        ),
        candidate_normalizer=normalizer,
        candidate_writer_service=_CandidateWriterService({"id": 88}),
        governor_service=_GovernorService(
            GovernanceDecision.model_validate(
                {
                    "governance_status": "needs_review",
                    "auto_apply_eligible": False,
                    "reason_code": "NON_OVERRIDE_TARGET_TYPE",
                }
            )
        ),
        candidate_repository=candidate_repository,
    )

    result = service.analyze_feedback(41)

    assert result.status == "completed"
    assert result.candidate_count == 0
    assert normalizer.calls == []
    assert candidate_repository.calls == []


def test_failure_analysis_service_marks_failed_when_pipeline_raises() -> None:
    analysis_repository = _PromptFailureAnalysisRepository()
    service = FailureAnalysisService(
        prompt_feedback_repository=_PromptFeedbackRepository(),
        analysis_repository=analysis_repository,
        prompt_artifact_bundle_service=_BundleService(error=ForgeError("missing artifacts", status_code=422)),
        evaluator_client=_EvaluatorClient(result=None),
        candidate_normalizer=_CandidateNormalizer(_normalized_candidate()),
        candidate_writer_service=_CandidateWriterService({"id": 88}),
        governor_service=_GovernorService(
            GovernanceDecision.model_validate(
                {
                    "governance_status": "needs_review",
                    "auto_apply_eligible": False,
                    "reason_code": "NON_OVERRIDE_TARGET_TYPE",
                }
            )
        ),
        candidate_repository=_CandidateRepository(),
    )

    try:
        service.analyze_feedback(41)
        assert False, "expected analyze_feedback to raise"
    except ForgeError as exc:
        assert exc.status_code == 422

    assert analysis_repository.failed_calls
    assert analysis_repository.failed_calls[0]["analysis_id"] == 55
    assert "missing artifacts" in analysis_repository.failed_calls[0]["error_message"]

from __future__ import annotations

from app.services.shared_ai.adapters.candidates import candidate_to_dict
from app.services.shared_ai.artifacts import (
    CandidateSetArtifact,
    ConfidenceArtifact,
    LLMDecisionArtifact,
    MatchOutcomeArtifact,
    RerankedCandidatesArtifact,
)
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode
from app.services.shared_ai.tracing import serialize_pipeline_context


class AssembleMatchOutcomeNode(BasePipelineNode):
    def __init__(
        self,
        *,
        name: str = "assemble_match_outcome",
        candidates_artifact_key: str = "reranked_candidates",
        decision_artifact_key: str = "llm_decision",
        confidence_artifact_key: str = "confidence",
        output_artifact_key: str = "match_outcome",
        include_pipeline_snapshot: bool = False,
    ) -> None:
        self.name = name
        self.requires = (candidates_artifact_key, decision_artifact_key, confidence_artifact_key)
        self.produces = (output_artifact_key,)
        self._candidates_artifact_key = candidates_artifact_key
        self._decision_artifact_key = decision_artifact_key
        self._confidence_artifact_key = confidence_artifact_key
        self._output_artifact_key = output_artifact_key
        self._include_pipeline_snapshot = bool(include_pipeline_snapshot)

    def run(self, context: PipelineContext) -> PipelineContext:
        candidate_set = context.get_artifact(self._candidates_artifact_key, node_name=self.name)
        decision = context.get_artifact(self._decision_artifact_key, node_name=self.name)
        confidence = context.get_artifact(self._confidence_artifact_key, node_name=self.name)
        if not isinstance(candidate_set, (CandidateSetArtifact, RerankedCandidatesArtifact)):
            raise TypeError(
                f"{self.name} expected CandidateSetArtifact or RerankedCandidatesArtifact at "
                f"'{self._candidates_artifact_key}'."
            )
        if not isinstance(decision, LLMDecisionArtifact):
            raise TypeError(f"{self.name} expected LLMDecisionArtifact at '{self._decision_artifact_key}'.")
        if not isinstance(confidence, ConfidenceArtifact):
            raise TypeError(f"{self.name} expected ConfidenceArtifact at '{self._confidence_artifact_key}'.")

        candidates = [candidate_to_dict(candidate) for candidate in list(candidate_set.candidates or [])]
        selected = _find_candidate(candidates, decision.selected_candidate_id)
        alternate_ids = list(decision.raw_payload.get("alternate_column_ids") or decision.ranked_candidate_ids[1:] or [])
        alternates = _find_alternates(candidates, alternate_ids)
        decision_payload = dict(decision.raw_payload or {})
        confidence_payload = dict(confidence.details or {})
        confidence_payload.setdefault("confidence_score", confidence.confidence_score)
        confidence_payload.setdefault("confidence_band", confidence.confidence_band)
        if self._include_pipeline_snapshot:
            decision_payload["shared_pipeline"] = serialize_pipeline_context(context)

        outcome = MatchOutcomeArtifact(
            selected_candidate=selected,
            alternates=alternates,
            candidates=candidates,
            decision_payload=decision_payload,
            confidence_payload=confidence_payload,
        )
        context.set_artifact(self._output_artifact_key, outcome)
        context.add_debug(
            self.name,
            {
                "selected_candidate_id": str(
                    decision.selected_candidate_id
                    or decision_payload.get("selected_column_id")
                    or ""
                ),
                "alternate_count": len(alternates),
                "candidate_count": len(candidates),
            },
        )
        return context


def _find_candidate(candidates: list[dict[str, object]], candidate_id: object) -> dict[str, object] | None:
    wanted = str(candidate_id or "").strip()
    if not wanted:
        return None
    for row in candidates:
        row_id = str(row.get("column_id") or row.get("candidate_id") or "").strip()
        if row_id == wanted:
            return row
    return None


def _find_alternates(candidates: list[dict[str, object]], candidate_ids: list[object]) -> list[dict[str, object]]:
    allowed = {str(value).strip() for value in list(candidate_ids or []) if str(value).strip()}
    out: list[dict[str, object]] = []
    for row in candidates:
        row_id = str(row.get("column_id") or row.get("candidate_id") or "").strip()
        if row_id in allowed:
            out.append(row)
        if len(out) >= 2:
            break
    return out

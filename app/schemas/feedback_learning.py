from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class RootCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    target: Optional[str] = None
    evidence: str

    @field_validator("type", "target", "evidence", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class ProposedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["semantic_override", "domain_override", "planner_rule", "manual_review"]
    target_key: str
    change_type: str
    payload: Dict[str, Any]
    risk_level: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("target_key", "change_type", mode="before")
    @classmethod
    def _strip_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if text == "":
            raise ValueError("value is required")
        return text

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("payload must be an object")
        return dict(value)


class EvaluatorAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["planner_error", "domain_error", "ambiguous", "inconclusive", "no_action"]
    failure_modes: list[str]
    root_causes: list[RootCause]
    proposed_changes: list[ProposedChange]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("failure_modes", mode="before")
    @classmethod
    def _normalize_failure_modes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("failure_modes must be a list")
        normalized: list[str] = []
        for item in value:
            token = str(item or "").strip()
            if token:
                normalized.append(token)
        return normalized


class PromptArtifactBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_feedback_id: int
    workspace_id: str
    user_id: str
    trace_id: Optional[str] = None
    conversation_id: Optional[str] = None
    prompt: str
    normalized_prompt: str
    planner_input: Dict[str, Any]
    planner_output: Dict[str, Any]
    generated_sql: Dict[str, Any]
    output_json: Dict[str, Any]
    candidate_domains: Optional[list[Dict[str, Any]]] = None
    candidate_concepts: Optional[list[Any]] = None
    selected_concepts: Optional[list[Any]] = None
    result_preview: Optional[Any] = None

    @field_validator("workspace_id", "user_id", "trace_id", "conversation_id", "prompt", "normalized_prompt", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("prompt", "normalized_prompt")
    @classmethod
    def _validate_required_text(cls, value: Optional[str]) -> str:
        if value is None or value == "":
            raise ValueError("value is required")
        return value

    @field_validator("planner_input", "planner_output", "generated_sql", "output_json")
    @classmethod
    def _validate_required_object(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("value must be a non-empty object")
        return dict(value)

    @field_validator("candidate_domains")
    @classmethod
    def _validate_candidate_domains(cls, value: Any) -> Optional[list[Dict[str, Any]]]:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("candidate_domains must be a list")
        out: list[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(dict(item))
        return out or None


class NormalizedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    failure_analysis_id: int
    target_type: Literal["semantic_override", "domain_override", "planner_rule", "manual_review"]
    concept_key: Optional[str] = None
    domain_key: Optional[str] = None
    change_type: str
    payload_json: Dict[str, Any]
    payload_hash: str
    risk_level: Literal["low", "medium", "high"]
    evidence_count: int = Field(ge=1, default=1)
    confidence: float = Field(ge=0.0, le=1.0)
    governance_status: Literal["pending", "auto_applied", "approved", "rejected", "needs_review"]
    auto_apply_eligible: bool = False
    governance_reason_code: Optional[str] = None
    review_notes: Optional[str] = None
    source_scope: Literal["global", "workspace"]
    workspace_id: Optional[str] = None
    workspace_scope_key: str

    @field_validator("concept_key", "domain_key", "change_type", "payload_hash", "workspace_id", "workspace_scope_key", "governance_reason_code", "review_notes", mode="before")
    @classmethod
    def _strip_candidate_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("change_type", "payload_hash", "workspace_scope_key")
    @classmethod
    def _validate_required_candidate_text(cls, value: Optional[str]) -> str:
        if value is None or value == "":
            raise ValueError("value is required")
        return value

    @field_validator("payload_json")
    @classmethod
    def _validate_payload_json(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("payload_json must be a non-empty object")
        return dict(value)


class GovernanceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    governance_status: Literal["pending", "rejected", "needs_review"]
    auto_apply_eligible: bool
    reason_code: str

    @field_validator("reason_code", mode="before")
    @classmethod
    def _validate_reason_code(cls, value: Any) -> str:
        text = str(value or "").strip()
        if text == "":
            raise ValueError("reason_code is required")
        return text


class AnalyzeFeedbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: int
    status: Literal["pending", "completed", "failed"]
    failure_verdict: Optional[str] = None
    candidate_count: int = Field(ge=0, default=0)

    @field_validator("failure_verdict", mode="before")
    @classmethod
    def _strip_failure_verdict(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = [
    "AnalyzeFeedbackResult",
    "EvaluatorAnalysis",
    "GovernanceDecision",
    "NormalizedCandidate",
    "PromptArtifactBundle",
    "ProposedChange",
    "RootCause",
    "ValidationError",
]

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class NormalizedTextArtifact:
    original_text: str
    normalized_text: str


@dataclass(frozen=True)
class PromptSignalsArtifact:
    source_text: str
    normalized_text: str
    signals: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    candidate_type: str
    label: str
    description: Optional[str] = None
    scores: dict[str, float] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateSetArtifact:
    candidates: list[Candidate] = field(default_factory=list)
    retrieval_debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityMapArtifact:
    candidate_capabilities: dict[str, list[str]] = field(default_factory=dict)
    capability_records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RerankedCandidatesArtifact:
    candidates: list[Candidate] = field(default_factory=list)
    policy_effects: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMDecisionArtifact:
    selected_candidate_id: Optional[str]
    ranked_candidate_ids: list[str] = field(default_factory=list)
    confidence: Optional[float] = None
    explanation: Optional[str] = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfidenceArtifact:
    confidence_score: int
    confidence_band: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationArtifact:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExplanationArtifact:
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

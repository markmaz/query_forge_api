from __future__ import annotations

from dataclasses import dataclass
import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class FeedbackLearningConfig:
    auto_apply_enabled: bool
    confidence_threshold: float
    evidence_threshold: int
    evaluator_max_retries: int
    workspace_overrides_enabled: bool
    domain_example_confidence_threshold: float


def load_feedback_learning_config() -> FeedbackLearningConfig:
    return FeedbackLearningConfig(
        auto_apply_enabled=_env_bool("FEEDBACK_AUTO_APPLY_ENABLED", True),
        confidence_threshold=_env_float("FEEDBACK_CONFIDENCE_THRESHOLD", 0.85),
        evidence_threshold=max(1, _env_int("FEEDBACK_EVIDENCE_THRESHOLD", 3)),
        evaluator_max_retries=max(0, _env_int("FEEDBACK_EVALUATOR_MAX_RETRIES", 2)),
        workspace_overrides_enabled=_env_bool("FEEDBACK_WORKSPACE_OVERRIDES_ENABLED", True),
        domain_example_confidence_threshold=_env_float("FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD", 0.90),
    )


FEEDBACK_LEARNING_CONFIG = load_feedback_learning_config()
FEEDBACK_AUTO_APPLY_ENABLED = FEEDBACK_LEARNING_CONFIG.auto_apply_enabled
FEEDBACK_CONFIDENCE_THRESHOLD = FEEDBACK_LEARNING_CONFIG.confidence_threshold
FEEDBACK_EVIDENCE_THRESHOLD = FEEDBACK_LEARNING_CONFIG.evidence_threshold
FEEDBACK_EVALUATOR_MAX_RETRIES = FEEDBACK_LEARNING_CONFIG.evaluator_max_retries
FEEDBACK_WORKSPACE_OVERRIDES_ENABLED = FEEDBACK_LEARNING_CONFIG.workspace_overrides_enabled
FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD = FEEDBACK_LEARNING_CONFIG.domain_example_confidence_threshold


__all__ = [
    "FEEDBACK_AUTO_APPLY_ENABLED",
    "FEEDBACK_CONFIDENCE_THRESHOLD",
    "FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD",
    "FEEDBACK_EVALUATOR_MAX_RETRIES",
    "FEEDBACK_EVIDENCE_THRESHOLD",
    "FEEDBACK_LEARNING_CONFIG",
    "FEEDBACK_WORKSPACE_OVERRIDES_ENABLED",
    "FeedbackLearningConfig",
    "load_feedback_learning_config",
]

from __future__ import annotations

from enum import Enum


class FeedbackType(str, Enum):
    thumbs_up = "thumbs_up"
    thumbs_down = "thumbs_down"


class FeedbackSubmissionStatus(str, Enum):
    recorded = "recorded"
    analysis_pending = "analysis_pending"


class AnalysisStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class GovernanceStatus(str, Enum):
    pending = "pending"
    auto_applied = "auto_applied"
    approved = "approved"
    rejected = "rejected"
    needs_review = "needs_review"


class OverrideStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TargetType(str, Enum):
    semantic_override = "semantic_override"
    domain_override = "domain_override"
    planner_rule = "planner_rule"
    manual_review = "manual_review"


class PromotionStatus(str, Enum):
    succeeded = "succeeded"
    failed = "failed"


AUTO_APPLY_CHANGE_TYPES = frozenset(
    {
        "add_alias",
        "add_phrase_hint",
        "concept_rank_boost",
        "concept_rank_penalty",
        "add_domain_example_prompt",
        "add_domain_lexical_hint",
        "add_ambiguity_note",
    }
)

BLOCKED_CHANGE_TYPES = frozenset(
    {
        "new_concept",
        "join_logic_change",
        "aggregation_change",
        "metric_definition_change",
    }
)

NON_OVERRIDE_TARGET_TYPES = frozenset(
    {
        TargetType.planner_rule,
        TargetType.manual_review,
    }
)

FEEDBACK_LEARNING_META_KEY = "_feedback_learning"


__all__ = [
    "AUTO_APPLY_CHANGE_TYPES",
    "BLOCKED_CHANGE_TYPES",
    "FEEDBACK_LEARNING_META_KEY",
    "NON_OVERRIDE_TARGET_TYPES",
    "AnalysisStatus",
    "FeedbackType",
    "FeedbackSubmissionStatus",
    "GovernanceStatus",
    "OverrideStatus",
    "PromotionStatus",
    "RiskLevel",
    "TargetType",
]

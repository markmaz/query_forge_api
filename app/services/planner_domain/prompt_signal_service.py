from __future__ import annotations

from typing import List, Optional, Set

from app.models.domain.planner_rerank_policy import PLANNER_RERANK_SIGNAL_KEYS
from app.services.domain.planner_signal_policy_service import PlannerSignalPolicyService
from app.services.planner_domain.prompt_intents import (
    _prompt_mentions_students,
)


class PromptSignalService:
    def __init__(self, *, policy_service: Optional[PlannerSignalPolicyService] = None) -> None:
        self._policy_service = policy_service or PlannerSignalPolicyService(enable_db_lookup=False)

    def extract_signals(self, *, prompt: str) -> List[str]:
        text = str(prompt or "").strip()
        lower = text.lower()
        if text == "":
            return []

        signals: Set[str] = set(self._policy_service.extract_policy_signals(prompt=text))

        if " by " in lower and "aggregate_intent" in signals:
            signals.add("grouped_aggregate")

        if "student_listing" in signals:
            signals.add("needs_student_identity")
        if "student_aggregate" in signals and "enrolled" in lower:
            signals.update({"needs_enrollment_status", "needs_student_identity"})
        if _prompt_mentions_students(text) and "school_literal_present" in signals:
            signals.add("student_listing")
            signals.add("listing_intent")
            signals.add("needs_student_identity")
        return sorted(signal for signal in signals if signal in PLANNER_RERANK_SIGNAL_KEYS)


__all__ = ["PromptSignalService"]

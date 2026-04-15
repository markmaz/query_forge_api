from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.domain.planner_domain_capability_service import PlannerDomainCapabilityService
from app.services.domain.planner_rerank_policy_service import PlannerRerankPolicyService
from app.services.planner_domain.prompt_signal_service import PromptSignalService

DEFAULT_MAX_POSITIVE_ADJUSTMENT = 0.6
DEFAULT_MAX_NEGATIVE_ADJUSTMENT = 0.6


class PlannerDomainRerankPolicyEngine:
    def __init__(
        self,
        *,
        prompt_signal_service: Optional[PromptSignalService] = None,
        capability_service: Optional[PlannerDomainCapabilityService] = None,
        policy_service: Optional[PlannerRerankPolicyService] = None,
    ) -> None:
        self._signals = prompt_signal_service or PromptSignalService()
        self._capabilities = capability_service or PlannerDomainCapabilityService()
        self._policies = policy_service or PlannerRerankPolicyService()

    def extract_prompt_signals(self, *, prompt: str) -> List[str]:
        return self._signals.extract_signals(prompt=prompt)

    @property
    def prompt_signal_service(self) -> PromptSignalService:
        return self._signals

    @property
    def capability_service(self) -> PlannerDomainCapabilityService:
        return self._capabilities

    @property
    def policy_service(self) -> PlannerRerankPolicyService:
        return self._policies

    def evaluate_candidate(
        self,
        *,
        prompt: str,
        workspace_id: str,
        base_domain_id: int,
        base_score: float,
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
        prompt_signals: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        signals = list(prompt_signals or self.extract_prompt_signals(prompt=prompt))
        signal_set = set(signals)
        capability_view = self._capabilities.resolve_capabilities(
            workspace_id=workspace_id,
            base_domain_id=base_domain_id,
            capabilities=capabilities,
            shortlisted_columns=shortlisted_columns,
        )
        present = set(capability_view["present"])

        policies = self._policies.get_applicable_policies(
            workspace_id=workspace_id,
            base_domain_id=base_domain_id,
        )
        policy_effects: List[Dict[str, Any]] = []
        total_adjustment = 0.0
        total_positive = 0.0
        total_negative = 0.0

        for row in policies:
            rule = dict(row.get("policy_json") or {})
            matched = _signals_match(rule=rule, signals=signal_set)
            if not matched:
                continue

            prefer_capabilities = [cap for cap in list(rule.get("prefer_capabilities") or []) if isinstance(cap, str)]
            penalize_missing = [cap for cap in list(rule.get("penalize_missing") or []) if isinstance(cap, str)]
            require_for_bonus = [cap for cap in list(rule.get("require_for_bonus") or []) if isinstance(cap, str)]

            matched_prefer = [cap for cap in prefer_capabilities if cap in present]
            missing_penalty = [cap for cap in penalize_missing if cap not in present]
            missing_required = [cap for cap in require_for_bonus if cap not in present]

            delta = 0.0
            boost = float(rule.get("boost") or 0.0)
            penalty = float(rule.get("penalty") or 0.0)
            max_effect = float(rule.get("max_effect") or 0.0)

            if not missing_required:
                if prefer_capabilities:
                    delta += boost * (len(matched_prefer) / float(len(prefer_capabilities)))
                elif boost > 0.0:
                    delta += boost
            if penalize_missing and missing_penalty:
                delta -= penalty * (len(missing_penalty) / float(len(penalize_missing)))

            if max_effect > 0.0:
                delta = max(-max_effect, min(max_effect, delta))

            if delta > 0:
                room = max(0.0, DEFAULT_MAX_POSITIVE_ADJUSTMENT - total_positive)
                delta = min(delta, room)
                total_positive += delta
            elif delta < 0:
                room = max(0.0, DEFAULT_MAX_NEGATIVE_ADJUSTMENT - total_negative)
                bounded = min(abs(delta), room)
                delta = -bounded
                total_negative += bounded

            total_adjustment += delta
            policy_effects.append(
                {
                    "policy_key": str(row.get("policy_key") or ""),
                    "matched": True,
                    "signals_matched": [
                        signal
                        for signal in list(rule.get("when_signals_all") or []) + list(rule.get("when_signals_any") or [])
                        if signal in signal_set
                    ],
                    "capabilities_present": sorted(set(matched_prefer + [cap for cap in require_for_bonus if cap in present])),
                    "capabilities_missing": sorted(set(missing_penalty + missing_required)),
                    "score_delta": round(delta, 5),
                    "reason": _build_reason(
                        policy_key=str(row.get("policy_key") or ""),
                        delta=delta,
                        present=sorted(set(matched_prefer + [cap for cap in require_for_bonus if cap in present])),
                        missing=sorted(set(missing_penalty + missing_required)),
                    ),
                }
            )
            if bool(row.get("stop_on_match")):
                break

        final_score = round(float(base_score) + total_adjustment, 5)
        return {
            "prompt_signals": signals,
            "domain_capabilities": {
                "present": capability_view["present"],
                "missing": sorted({cap for effect in policy_effects for cap in effect["capabilities_missing"]}),
            },
            "capability_records": capability_view["records"],
            "policy_effects": policy_effects,
            "rerank_summary": {
                "base_score": round(float(base_score), 5),
                "policy_adjustment": round(total_adjustment, 5),
                "final_score": final_score,
            },
            "final_score": final_score,
        }


def _signals_match(*, rule: Mapping[str, Any], signals: set[str]) -> bool:
    signals_all = [str(item) for item in list(rule.get("when_signals_all") or []) if str(item).strip()]
    signals_any = [str(item) for item in list(rule.get("when_signals_any") or []) if str(item).strip()]
    exclude_any = [str(item) for item in list(rule.get("exclude_signals_any") or []) if str(item).strip()]

    if signals_all and any(signal not in signals for signal in signals_all):
        return False
    if signals_any and not any(signal in signals for signal in signals_any):
        return False
    if exclude_any and any(signal in signals for signal in exclude_any):
        return False
    return True


def _build_reason(*, policy_key: str, delta: float, present: Sequence[str], missing: Sequence[str]) -> str:
    if delta > 0:
        if present:
            return f"Boosted by {policy_key} because domain supports {', '.join(present)}."
        return f"Boosted by {policy_key}."
    if delta < 0:
        if missing:
            return f"Penalized by {policy_key} because domain lacks {', '.join(missing)}."
        return f"Penalized by {policy_key}."
    if missing:
        return f"{policy_key} matched but produced no score change because required capabilities were missing."
    return f"{policy_key} matched but produced no score change."


__all__ = ["PlannerDomainRerankPolicyEngine"]

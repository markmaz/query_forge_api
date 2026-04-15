from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Protocol, Sequence

from app.services.domain.planner_rerank_policy_service import PlannerRerankPolicyService
from app.services.planner_domain.rerank_policy_engine import (
    DEFAULT_MAX_NEGATIVE_ADJUSTMENT,
    DEFAULT_MAX_POSITIVE_ADJUSTMENT,
)
from app.services.shared_ai.artifacts import Candidate, CapabilityMapArtifact, PromptSignalsArtifact, RerankedCandidatesArtifact
from app.services.shared_ai.context import PipelineContext

FORGE_MATCH_PREFERRED_DOMAIN_BONUS = 0.08
NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


class CandidatePolicyRerankAdapter(Protocol):
    def rerank(
        self,
        *,
        context: PipelineContext,
        candidates: Sequence[Candidate],
        prompt_signals: PromptSignalsArtifact,
        capability_map: CapabilityMapArtifact,
    ) -> RerankedCandidatesArtifact:
        ...


class PolicyDrivenRerankAdapter:
    def __init__(self, *, policy_provider: PlannerRerankPolicyService | None = None) -> None:
        self._policies = policy_provider or PlannerRerankPolicyService()

    def rerank(
        self,
        *,
        context: PipelineContext,
        candidates: Sequence[Candidate],
        prompt_signals: PromptSignalsArtifact,
        capability_map: CapabilityMapArtifact,
    ) -> RerankedCandidatesArtifact:
        workspace_id = str(context.workspace_id or "").strip()
        reranked: list[Candidate] = []
        effects: list[dict[str, Any]] = []

        for candidate in candidates:
            base_domain_id = int(candidate.attributes.get("domain_id") or candidate.attributes.get("base_domain_id") or 0)
            base_score = _candidate_base_score(candidate)
            present = set(capability_map.candidate_capabilities.get(candidate.candidate_id) or list(candidate.capabilities))
            adjustment = 0.0
            positive = 0.0
            negative = 0.0
            candidate_effects: list[dict[str, Any]] = []
            domain_preference_adjustment = 0.0

            if workspace_id and base_domain_id > 0:
                policies = self._policies.get_applicable_policies(
                    workspace_id=workspace_id,
                    base_domain_id=base_domain_id,
                )
                for row in policies:
                    rule = dict(row.get("policy_json") or {})
                    if not _signals_match(rule=rule, signals=set(prompt_signals.signals)):
                        continue

                    prefer = [str(item) for item in list(rule.get("prefer_capabilities") or []) if str(item).strip()]
                    penalize = [str(item) for item in list(rule.get("penalize_missing") or []) if str(item).strip()]
                    require = [str(item) for item in list(rule.get("require_for_bonus") or []) if str(item).strip()]

                    matched_prefer = [cap for cap in prefer if cap in present]
                    missing_penalty = [cap for cap in penalize if cap not in present]
                    missing_required = [cap for cap in require if cap not in present]

                    delta = 0.0
                    boost = float(rule.get("boost") or 0.0)
                    penalty = float(rule.get("penalty") or 0.0)
                    max_effect = float(rule.get("max_effect") or 0.0)

                    if not missing_required:
                        if prefer:
                            delta += boost * (len(matched_prefer) / float(len(prefer)))
                        elif boost > 0.0:
                            delta += boost
                    if penalize and missing_penalty:
                        delta -= penalty * (len(missing_penalty) / float(len(penalize)))

                    if max_effect > 0.0:
                        delta = max(-max_effect, min(max_effect, delta))

                    if delta > 0:
                        room = max(0.0, DEFAULT_MAX_POSITIVE_ADJUSTMENT - positive)
                        delta = min(delta, room)
                        positive += delta
                    elif delta < 0:
                        room = max(0.0, DEFAULT_MAX_NEGATIVE_ADJUSTMENT - negative)
                        bounded = min(abs(delta), room)
                        delta = -bounded
                        negative += bounded

                    adjustment += delta
                    candidate_effects.append(
                        {
                            "candidate_id": candidate.candidate_id,
                            "candidate_label": candidate.label,
                            "policy_key": str(row.get("policy_key") or ""),
                            "score_delta": round(delta, 5),
                            "signals_matched": [
                                signal
                                for signal in list(rule.get("when_signals_all") or []) + list(rule.get("when_signals_any") or [])
                                if signal in set(prompt_signals.signals)
                            ],
                            "capabilities_present": sorted(set(matched_prefer + [cap for cap in require if cap in present])),
                            "capabilities_missing": sorted(set(missing_penalty + missing_required)),
                            "reason": _build_reason(
                                policy_key=str(row.get("policy_key") or ""),
                                delta=delta,
                                present=sorted(set(matched_prefer + [cap for cap in require if cap in present])),
                                missing=sorted(set(missing_penalty + missing_required)),
                            ),
                        }
                    )
                    if bool(row.get("stop_on_match")):
                        break

            preferred_domain_id = _preferred_domain_id(context)
            if preferred_domain_id is not None and candidate.candidate_type == "column" and base_domain_id == preferred_domain_id:
                domain_preference_adjustment = FORGE_MATCH_PREFERRED_DOMAIN_BONUS
                adjustment += domain_preference_adjustment
                candidate_effects.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "candidate_label": candidate.label,
                        "policy_key": "preferred_domain_bias",
                        "score_delta": round(domain_preference_adjustment, 5),
                        "signals_matched": [],
                        "capabilities_present": [],
                        "capabilities_missing": [],
                        "reason": "Boosted because candidate belongs to the preferred Forge Match domain.",
                    }
                )

            final_score = round(base_score + adjustment, 5)
            reranked.append(
                replace(
                    candidate,
                    attributes={
                        **candidate.attributes,
                        "preferred_domain_match": preferred_domain_id is not None and base_domain_id == preferred_domain_id,
                    },
                    scores={
                        **candidate.scores,
                        "base_score": round(base_score, 5),
                        "policy_adjustment": round(adjustment, 5),
                        "domain_preference_adjustment": round(domain_preference_adjustment, 5),
                        "final_score": final_score,
                    },
                )
            )
            if candidate_effects:
                effects.extend(candidate_effects)

        reranked.sort(
            key=lambda item: (
                float(item.scores.get("final_score") or _candidate_base_score(item)),
                float(item.scores.get("combined_retrieval_score") or 0.0),
                float(item.scores.get("lexical_score") or 0.0),
                float(item.scores.get("vector_score") or 0.0),
            ),
            reverse=True,
        )

        return RerankedCandidatesArtifact(
            candidates=reranked,
            policy_effects=effects,
            summary={
                "signals": list(prompt_signals.signals),
                "candidate_count": len(reranked),
                "policy_match_count": len(effects),
                "preferred_domain_id": _preferred_domain_id(context),
            },
        )

def _candidate_base_score(candidate: Candidate) -> float:
    for key in ("final_score", "base_score", "combined_retrieval_score", "score", "vector_score", "lexical_score"):
        raw = candidate.scores.get(key)
        try:
            if raw is not None:
                return float(raw)
        except NUMERIC_PARSE_ERRORS:
            continue
    return 0.0


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
            return f"Boosted by {policy_key} because candidate supports {', '.join(present)}."
        return f"Boosted by {policy_key}."
    if delta < 0:
        if missing:
            return f"Penalized by {policy_key} because candidate lacks {', '.join(missing)}."
        return f"Penalized by {policy_key}."
    if missing:
        return f"{policy_key} matched but produced no score change because required capabilities were missing."
    return f"{policy_key} matched but produced no score change."


def _preferred_domain_id(context: PipelineContext) -> int | None:
    raw = context.request.get("preferred_domain_id")
    if raw is None:
        return None
    try:
        parsed = int(raw)
    except NUMERIC_PARSE_ERRORS:
        return None
    return parsed if parsed > 0 else None


class SignalCapabilityRerankAdapter:
    def rerank(
        self,
        *,
        context: PipelineContext,
        candidates: Sequence[Candidate],
        prompt_signals: PromptSignalsArtifact,
        capability_map: CapabilityMapArtifact,
    ) -> RerankedCandidatesArtifact:
        del context
        signals = set(prompt_signals.signals)
        reranked: list[Candidate] = []
        effects: list[dict[str, Any]] = []

        for candidate in candidates:
            base_score = _candidate_base_score(candidate)
            present = set(capability_map.candidate_capabilities.get(candidate.candidate_id) or list(candidate.capabilities))
            adjustment, candidate_effects = _heuristic_capability_adjustment(
                candidate=candidate,
                signals=signals,
                capabilities=present,
            )
            final_score = round(base_score + adjustment, 5)
            reranked.append(
                replace(
                    candidate,
                    attributes={
                        **candidate.attributes,
                        "preferred_domain_match": False,
                    },
                    scores={
                        **candidate.scores,
                        "base_score": round(base_score, 5),
                        "policy_adjustment": round(adjustment, 5),
                        "domain_preference_adjustment": 0.0,
                        "final_score": final_score,
                    },
                )
            )
            if candidate_effects:
                effects.extend(candidate_effects)

        reranked.sort(
            key=lambda item: (
                float(item.scores.get("final_score") or _candidate_base_score(item)),
                float(item.scores.get("combined_retrieval_score") or 0.0),
                float(item.scores.get("lexical_score") or 0.0),
                float(item.scores.get("vector_score") or 0.0),
            ),
            reverse=True,
        )

        return RerankedCandidatesArtifact(
            candidates=reranked,
            policy_effects=effects,
            summary={
                "signals": list(prompt_signals.signals),
                "candidate_count": len(reranked),
                "policy_match_count": len(effects),
                "mode": "signal_capability_rerank",
            },
        )


def _heuristic_capability_adjustment(
    *,
    candidate: Candidate,
    signals: set[str],
    capabilities: set[str],
) -> tuple[float, list[dict[str, Any]]]:
    adjustment = 0.0
    effects: list[dict[str, Any]] = []

    def apply(delta: float, reason: str, matched_caps: Sequence[str]) -> None:
        nonlocal adjustment
        if abs(delta) <= 0:
            return
        adjustment += delta
        effects.append(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_label": candidate.label,
                "policy_key": "forge_match_signal_capability",
                "score_delta": round(delta, 5),
                "signals_matched": sorted(signals),
                "capabilities_present": sorted(matched_caps),
                "capabilities_missing": [],
                "reason": reason,
            }
        )

    if "age_extreme_prompt" in signals:
        if "BIRTH_DATE" in capabilities:
            apply(0.28, "Boosted because age-extreme prompts align strongly with birth-date columns.", ["BIRTH_DATE"])
        elif "AGE" in capabilities:
            apply(0.22, "Boosted because age-extreme prompts align with age columns.", ["AGE"])
        elif "PROGRAM_MEMBERSHIP" in capabilities:
            apply(-0.18, "Penalized because program-membership columns are weak fits for age-extreme prompts.", ["PROGRAM_MEMBERSHIP"])

    if "birth_month_prompt" in signals:
        if "BIRTH_DATE" in capabilities:
            apply(0.32, "Boosted because birth-month prompts align strongly with birth-date columns.", ["BIRTH_DATE"])
        elif "PROGRAM_MEMBERSHIP" in capabilities:
            apply(-0.16, "Penalized because program-membership columns are weak fits for birth-month prompts.", ["PROGRAM_MEMBERSHIP"])

    if "calendar_days_off_prompt" in signals:
        matched = [cap for cap in ("SCHOOL_DAY_FLAG", "NON_INSTRUCTIONAL_DAY", "CALENDAR_DATE") if cap in capabilities]
        if matched:
            delta = 0.0
            if "SCHOOL_DAY_FLAG" in capabilities:
                delta += 0.24
            if "NON_INSTRUCTIONAL_DAY" in capabilities:
                delta += 0.24
            if "CALENDAR_DATE" in capabilities:
                delta += 0.14
            apply(min(delta, 0.34), "Boosted because days-off prompts align with calendar/day-off columns.", matched)
        elif "PROGRAM_MEMBERSHIP" in capabilities:
            apply(-0.18, "Penalized because program-membership columns are weak fits for calendar day-off prompts.", ["PROGRAM_MEMBERSHIP"])

    if "student_listing" in signals and "STUDENT_IDENTITY" in capabilities:
        apply(0.06, "Boosted because student-listing prompts align with student identity columns.", ["STUDENT_IDENTITY"])

    return adjustment, effects

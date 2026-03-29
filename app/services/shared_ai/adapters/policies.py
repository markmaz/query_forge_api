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


class PlannerPolicyRerankAdapter:
    def __init__(self, *, policy_service: PlannerRerankPolicyService | None = None) -> None:
        self._policies = policy_service or PlannerRerankPolicyService()

    def rerank(
        self,
        *,
        context: PipelineContext,
        candidates: Sequence[Candidate],
        prompt_signals: PromptSignalsArtifact,
        capability_map: CapabilityMapArtifact,
    ) -> RerankedCandidatesArtifact:
        workspace_id = str(context.workspace_id or "").strip()
        vertical_norm = str(context.vertical_norm or "generic")
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

            if workspace_id and base_domain_id > 0:
                policies = self._policies.get_applicable_policies(
                    workspace_id=workspace_id,
                    vertical_norm=vertical_norm,
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

            final_score = round(base_score + adjustment, 5)
            reranked.append(
                replace(
                    candidate,
                    scores={
                        **candidate.scores,
                        "base_score": round(base_score, 5),
                        "policy_adjustment": round(adjustment, 5),
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
            },
        )


def _candidate_base_score(candidate: Candidate) -> float:
    for key in ("final_score", "base_score", "combined_retrieval_score", "score", "vector_score", "lexical_score"):
        raw = candidate.scores.get(key)
        try:
            if raw is not None:
                return float(raw)
        except Exception:
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

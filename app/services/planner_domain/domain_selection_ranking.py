"""Rerank and selection helpers for planner-domain selection."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.config import QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED
from app.exceptions.forge_error import ForgeError
from app.services.shared_ai.adapters.candidates import candidate_from_domain_row
from app.services.shared_ai.artifacts import CandidateSetArtifact, PromptSignalsArtifact, RerankedCandidatesArtifact
from app.services.shared_ai.context import PipelineContext


def select_domain_and_shortlist_columns(
    *,
    workspace_id: str,
    user_id: str,
    vertical_norm: str,
    prompt: str,
    domain_candidates: Sequence[Mapping[str, Any]],
    get_domain_capabilities_fn: Callable[..., Mapping[str, Any]],
    shortlist_columns_fn: Callable[..., List[Dict[str, Any]]],
    compact_capabilities_fn: Callable[..., Dict[str, Any]],
    semantic_grounding_factory: Callable[[], Any],
    score_semantic_grounding_bundle_fn: Callable[..., float],
    score_domain_candidate_fn: Callable[..., float],
    domain_selection_policy_service: Any,
    projection_policy_service: Any,
    planner_capability_adapter: Any,
    planner_policy_adapter: Any,
    pipeline_executor: Any,
    pipeline_definition_factory: Callable[..., Any],
) -> Tuple[Optional[PipelineContext], int, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    ranking_seed_rows: List[Dict[str, Any]] = []
    first_error: Optional[ForgeError] = None

    for candidate in list(domain_candidates or [])[:3]:
        domain_id = int(candidate.get("domain_id") or 0)
        if domain_id <= 0:
            continue
        try:
            capabilities = get_domain_capabilities_fn(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=domain_id,
                vertical_norm=vertical_norm,
            )
        except ForgeError as exc:
            if first_error is None:
                first_error = exc
            ranking_seed_rows.append({"domain_id": domain_id, "status": "error", "error": str(exc), "score": 0.0})
            continue

        shortlist = shortlist_columns_fn(
            prompt=prompt,
            workspace_id=workspace_id,
            capabilities=capabilities,
        )
        semantic_score = 0.0
        if QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
            semantic_capabilities = compact_capabilities_fn(
                capabilities,
                shortlist,
                prompt,
                slot_hints=None,
                fast_mode=False,
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                projection_policy_service=projection_policy_service,
            )
            grounding_bundle = semantic_grounding_factory().build_grounding_bundle(
                prompt=prompt,
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                base_domain_id=domain_id,
                base_domain_name=str(candidate.get("name") or f"domain_{domain_id}"),
                capabilities_compact=semantic_capabilities,
                include_candidates=True,
                include_alias_constraints=True,
            )
            semantic_score = score_semantic_grounding_bundle_fn(
                prompt=prompt,
                grounding_bundle=grounding_bundle,
            )
        score = score_domain_candidate_fn(
            prompt=prompt,
            candidate=candidate,
            capabilities=capabilities,
            shortlisted_columns=shortlist,
            selection_policy_service=domain_selection_policy_service,
        )
        base_score = round(score + semantic_score, 5)
        ranking_seed_rows.append(
            {
                "domain_id": domain_id,
                "name": str(candidate.get("name") or f"domain_{domain_id}"),
                "score": base_score,
                "base_score": base_score,
                "semantic_score": semantic_score,
                "vector_score": float(candidate.get("score") or 0.0),
                "source": str(candidate.get("source") or "vector"),
                "capabilities_payload": capabilities,
                "shortlisted_columns": shortlist,
                "column_shortlist_count": len(shortlist),
                "dimension_count": len(list(capabilities.get("dimensions") or [])),
            }
        )

    successful_seed_rows = [row for row in ranking_seed_rows if str(row.get("status") or "") != "error"]
    if not successful_seed_rows:
        if first_error is not None:
            raise first_error
        raise ForgeError("No accessible domain candidates found", status_code=404)

    pipeline_context = PipelineContext(
        pipeline_name="planner_domain_selection_pipeline",
        trace_id=f"planner_domain_selection:{workspace_id}:{vertical_norm}",
        workspace_id=workspace_id,
        user_id=user_id,
        vertical_norm=vertical_norm,
        request={"prompt": prompt},
    )
    pipeline_context.set_artifact(
        "candidate_set",
        CandidateSetArtifact(
            candidates=[candidate_from_domain_row(row) for row in successful_seed_rows],
            retrieval_debug={"candidate_count": len(successful_seed_rows)},
        ),
    )
    pipeline_definition = pipeline_definition_factory(
        capability_adapter=planner_capability_adapter,
        policy_adapter=planner_policy_adapter,
    )
    pipeline_context = pipeline_executor.execute(pipeline_definition, pipeline_context)

    prompt_signals_artifact = pipeline_context.get_artifact(
        "prompt_signals",
        node_name="planner_domain_selection_pipeline",
    )
    reranked_artifact = pipeline_context.get_artifact(
        "reranked_candidates",
        node_name="planner_domain_selection_pipeline",
    )
    if not isinstance(prompt_signals_artifact, PromptSignalsArtifact):
        raise TypeError("planner_domain_selection_pipeline expected PromptSignalsArtifact.")
    if not isinstance(reranked_artifact, RerankedCandidatesArtifact):
        raise TypeError("planner_domain_selection_pipeline expected RerankedCandidatesArtifact.")

    effects_by_candidate: Dict[str, List[Dict[str, Any]]] = {}
    for effect in list(reranked_artifact.policy_effects or []):
        candidate_id = str(effect.get("candidate_id") or "").strip()
        if candidate_id == "":
            continue
        effects_by_candidate.setdefault(candidate_id, []).append(dict(effect))

    ranking: List[Dict[str, Any]] = []
    best_row: Optional[Dict[str, Any]] = None
    for candidate_artifact in reranked_artifact.candidates:
        attrs = dict(candidate_artifact.attributes)
        domain_id = int(attrs.get("domain_id") or 0)
        candidate_effects = list(effects_by_candidate.get(candidate_artifact.candidate_id) or [])
        present_capabilities = list(candidate_artifact.capabilities or [])
        row = {
            "domain_id": domain_id,
            "score": float(candidate_artifact.scores.get("final_score") or candidate_artifact.scores.get("base_score") or 0.0),
            "base_score": float(candidate_artifact.scores.get("base_score") or 0.0),
            "semantic_score": float(attrs.get("semantic_score") or 0.0),
            "vector_score": float(attrs.get("vector_score") or 0.0),
            "policy_adjustment": float(candidate_artifact.scores.get("policy_adjustment") or 0.0),
            "rerank_signals": list(prompt_signals_artifact.signals),
            "domain_capabilities": {
                "present": present_capabilities,
                "missing": sorted(
                    {
                        capability
                        for effect in candidate_effects
                        for capability in list(effect.get("capabilities_missing") or [])
                    }
                ),
            },
            "policy_effects": candidate_effects,
            "rerank_summary": {
                "base_score": round(float(candidate_artifact.scores.get("base_score") or 0.0), 5),
                "policy_adjustment": round(float(candidate_artifact.scores.get("policy_adjustment") or 0.0), 5),
                "final_score": round(
                    float(candidate_artifact.scores.get("final_score") or candidate_artifact.scores.get("base_score") or 0.0),
                    5,
                ),
            },
            "column_shortlist_count": int(attrs.get("column_shortlist_count") or 0),
            "dimension_count": int(attrs.get("dimension_count") or 0),
            "source": str(attrs.get("source") or "vector"),
            "capabilities": dict(attrs.get("capabilities_payload") or {}),
            "shortlisted_columns": list(attrs.get("shortlisted_columns") or []),
        }
        ranking.append({k: v for k, v in row.items() if k not in {"capabilities", "shortlisted_columns"}})
        if best_row is None or float(row["score"]) > float(best_row["score"]):
            best_row = row

    return (
        pipeline_context,
        int(best_row["domain_id"]),
        dict(best_row["capabilities"]),
        list(best_row["shortlisted_columns"]),
        ranking,
        list(prompt_signals_artifact.signals),
    )

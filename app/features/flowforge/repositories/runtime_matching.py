from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, lastrowid as _lastrowid


class FlowForgeRuntimeMatchingRepositoryMixin:
    def create_matching_evaluation(
        self,
        *,
        workspace_id: str,
        run_id: int,
        matching_policy_version_id: int,
        resource_set_id: int,
        snapshot_batch_id: int,
        input_context: dict[str, Any],
        summary: dict[str, Any],
        selected_source_record_key: str | None,
        no_match_reason: str | None,
        status: str,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_matching_evaluations (
              workspace_id,
              run_id,
              matching_policy_version_id,
              resource_set_id,
              snapshot_batch_id,
              input_context_json,
              summary_json,
              selected_source_record_key,
              no_match_reason,
              status
            ) VALUES (
              :workspace_id,
              :run_id,
              :matching_policy_version_id,
              :resource_set_id,
              :snapshot_batch_id,
              :input_context_json,
              :summary_json,
              :selected_source_record_key,
              :no_match_reason,
              :status
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "matching_policy_version_id": int(matching_policy_version_id),
                "resource_set_id": int(resource_set_id),
                "snapshot_batch_id": int(snapshot_batch_id),
                "input_context_json": _json_or_none(input_context),
                "summary_json": _json_or_none(summary),
                "selected_source_record_key": selected_source_record_key,
                "no_match_reason": no_match_reason,
                "status": str(status or "completed").strip(),
            },
        )
        return _lastrowid(result)

    def create_matching_evaluation_candidate(
        self,
        *,
        workspace_id: str,
        matching_evaluation_id: int,
        resource_set_id: int,
        candidate: dict[str, Any],
        selected: bool,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_matching_evaluation_candidates (
              workspace_id,
              matching_evaluation_id,
              resource_set_id,
              source_record_key,
              included,
              excluded,
              selected,
              rank_position,
              score,
              eligibility_result_json,
              score_breakdown_json,
              explanation_json
            ) VALUES (
              :workspace_id,
              :matching_evaluation_id,
              :resource_set_id,
              :source_record_key,
              :included,
              :excluded,
              :selected,
              :rank_position,
              :score,
              :eligibility_result_json,
              :score_breakdown_json,
              :explanation_json
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_evaluation_id": int(matching_evaluation_id),
                "resource_set_id": int(resource_set_id),
                "source_record_key": str(candidate.get("source_record_key") or "").strip(),
                "included": 1 if candidate.get("included") else 0,
                "excluded": 1 if candidate.get("excluded") else 0,
                "selected": 1 if selected else 0,
                "rank_position": candidate.get("rank_position"),
                "score": candidate.get("score"),
                "eligibility_result_json": _json_or_none(candidate.get("eligibility_result") or []),
                "score_breakdown_json": _json_or_none(candidate.get("score_breakdown") or []),
                "explanation_json": _json_or_none(
                    {
                        "explanation": candidate.get("explanation"),
                        "exclusion_reasons": candidate.get("exclusion_reasons") or [],
                    }
                ),
            },
        )
        return _lastrowid(result)

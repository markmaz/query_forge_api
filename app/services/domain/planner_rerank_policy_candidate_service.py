from __future__ import annotations

import json
from json import JSONDecodeError
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.planner_rerank_policy import (
    PLANNER_RERANK_CANDIDATE_REVIEW_STATUSES,
    PlannerRerankPolicyCandidateApproveRequest,
    PlannerRerankPolicyCandidateCreateRequest,
    PlannerRerankPolicyRule,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.planner_rerank_policy_service import PlannerRerankPolicyService


class PlannerRerankPolicyCandidateService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        policy_service: Optional[PlannerRerankPolicyService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._policies = policy_service or PlannerRerankPolicyService(sql=self._sql)

    def list_candidates(
        self,
        *,
        workspace_id: str,
        review_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        status = self._normalize_review_status(review_status) if review_status else None
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              id,
              candidate_key,
              source_type,
              workspace_id,
              candidate_json,
              rationale_json,
              confidence,
              review_status,
              approved_policy_id,
              created_at,
              updated_at
            FROM planner_rerank_policy_candidate
            WHERE (
              workspace_id IS NULL
              OR workspace_id = :workspace_id
            )
            {"AND review_status = :review_status" if status else ""}
            ORDER BY created_at DESC, id DESC
            """,
            {
                "workspace_id": str(workspace_id),
                "review_status": status,
            },
        )
        candidates: List[Dict[str, Any]] = []
        for row in rows:
            payload = _json_safe_mapping(dict(row))
            payload["candidate_json"] = _parse_candidate_policy(payload.get("candidate_json")).model_dump()
            candidates.append(payload)
        return {
            "workspace_id": str(workspace_id),
            "review_status": status,
            "candidates": candidates,
        }

    def create_candidate(
        self,
        *,
        workspace_id: str,
        payload: Any,
    ) -> Dict[str, Any]:
        req = PlannerRerankPolicyCandidateCreateRequest.model_validate(payload)
        if req.workspace_id and req.workspace_id != workspace_id:
            raise ForgeError("candidate workspace_id must match the active workspace", status_code=400)
        existing_row: Optional[Dict[str, Any]] = None
        if req.id is not None:
            existing_row = self._load_candidate(candidate_id=int(req.id), workspace_id=workspace_id)
        params = {
            "candidate_key": req.candidate_key,
            "source_type": req.source_type,
            "workspace_id": req.workspace_id or workspace_id,
            "candidate_json": json.dumps(req.candidate_policy.model_dump()),
            "rationale_json": json.dumps(req.rationale_json) if req.rationale_json is not None else None,
            "confidence": req.confidence,
        }
        with self._sql.transaction() as tx:
            if existing_row:
                tx.execute_write(
                    """
                    UPDATE planner_rerank_policy_candidate
                    SET candidate_key = :candidate_key,
                        source_type = :source_type,
                        workspace_id = :workspace_id,
                        candidate_json = :candidate_json,
                        rationale_json = :rationale_json,
                        confidence = :confidence,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :candidate_id
                    """,
                    {**params, "candidate_id": int(existing_row["id"])},
                )
                candidate_id = int(existing_row["id"])
                review_status = str(existing_row.get("review_status") or "pending").strip().lower() or "pending"
                approved_policy_id = existing_row.get("approved_policy_id")
            else:
                insert_result = tx.execute_insert(
                    """
                    INSERT INTO planner_rerank_policy_candidate (
                      candidate_key,
                      source_type,
                      workspace_id,
                      candidate_json,
                      rationale_json,
                      confidence,
                      review_status
                    ) VALUES (
                      :candidate_key,
                      :source_type,
                      :workspace_id,
                      :candidate_json,
                      :rationale_json,
                      :confidence,
                      'pending'
                    )
                    """,
                    params,
                )
                candidate_id = int(getattr(insert_result, "lastrowid", 0) or 0)
                if candidate_id <= 0:
                    rows = self._sql.execute_query_mappings(
                        """
                        SELECT id
                        FROM planner_rerank_policy_candidate
                        WHERE candidate_key = :candidate_key
                          AND workspace_id = :workspace_id
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    candidate_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if candidate_id <= 0:
                    raise ForgeError("Unable to resolve planner rerank policy candidate id after insert.", status_code=500)
                review_status = "pending"
                approved_policy_id = None
        return {
            "candidate_id": candidate_id,
            "candidate_key": req.candidate_key,
            "source_type": req.source_type,
            "workspace_id": req.workspace_id or workspace_id,
            "candidate_json": req.candidate_policy.model_dump(),
            "rationale_json": req.rationale_json,
            "confidence": req.confidence,
            "review_status": review_status,
            "approved_policy_id": int(approved_policy_id) if approved_policy_id is not None else None,
        }

    def delete_candidate(
        self,
        *,
        workspace_id: str,
        candidate_id: int,
    ) -> Dict[str, Any]:
        self._load_candidate(candidate_id=candidate_id, workspace_id=workspace_id)
        deleted = self._sql.execute_write(
            "DELETE FROM planner_rerank_policy_candidate WHERE id = :candidate_id",
            {"candidate_id": int(candidate_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner rerank policy candidate not found", status_code=404)
        return {
            "deleted": True,
            "candidate_id": int(candidate_id),
        }

    def approve_candidate(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        candidate_id: int,
        payload: Any,
    ) -> Dict[str, Any]:
        approval = PlannerRerankPolicyCandidateApproveRequest.model_validate(payload)
        candidate = self._load_candidate(candidate_id=candidate_id, workspace_id=workspace_id)
        if str(candidate.get("review_status") or "").strip().lower() == "approved":
            raise ForgeError("Candidate has already been approved", status_code=400)

        candidate_policy = _parse_candidate_policy(candidate.get("candidate_json")).model_dump()
        policy_payload = {
            "policy_key": approval.policy_key or str(candidate.get("candidate_key") or "").strip(),
            "name": approval.name,
            "description": approval.description,
            "scope_type": approval.scope_type,
            "scope_workspace_id": approval.scope_workspace_id,
            "scope_base_domain_id": approval.scope_base_domain_id,
            "priority": approval.priority,
            "is_active": approval.is_active,
            "stop_on_match": approval.stop_on_match,
            "policy_json": candidate_policy,
        }
        policy_row = self._policies.upsert_policy(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            payload=policy_payload,
        )
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                UPDATE planner_rerank_policy_candidate
                SET review_status = 'approved',
                    approved_policy_id = :approved_policy_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :candidate_id
                """,
                {
                    "candidate_id": int(candidate_id),
                    "approved_policy_id": int(policy_row["policy_id"]),
                },
            )
        return {
            "candidate_id": int(candidate_id),
            "review_status": "approved",
            "approved_policy_id": int(policy_row["policy_id"]),
            "policy": policy_row,
        }

    def _load_candidate(self, *, candidate_id: int, workspace_id: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              candidate_key,
              source_type,
              workspace_id,
              candidate_json,
              rationale_json,
              confidence,
              review_status,
              approved_policy_id
            FROM planner_rerank_policy_candidate
            WHERE id = :candidate_id
              AND (
                workspace_id IS NULL
                OR workspace_id = :workspace_id
              )
            LIMIT 1
            """,
            {
                "candidate_id": int(candidate_id),
                "workspace_id": str(workspace_id),
            },
        )
        if not rows:
            raise ForgeError("Planner rerank policy candidate not found", status_code=404)
        return dict(rows[0])

    @staticmethod
    def _normalize_review_status(value: str) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_RERANK_CANDIDATE_REVIEW_STATUSES:
            raise ForgeError("review_status must be pending, approved, or rejected", status_code=400)
        return token


def _parse_candidate_policy(value: Any) -> PlannerRerankPolicyRule:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ForgeError(f"Invalid planner rerank policy candidate JSON: {exc}", status_code=500)
    try:
        return PlannerRerankPolicyRule.model_validate(raw or {})
    except (ValidationError, TypeError, ValueError) as exc:
        raise ForgeError(f"Invalid planner rerank policy candidate JSON: {exc}", status_code=500)


def _json_safe_mapping(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


__all__ = ["PlannerRerankPolicyCandidateService"]

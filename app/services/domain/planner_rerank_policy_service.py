from __future__ import annotations

import json
from json import JSONDecodeError
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.planner_rerank_policy import (
    PLANNER_RERANK_SCOPE_TYPES,
    PlannerRerankPolicyRule,
    PlannerRerankPolicyUpsertRequest,
)
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

POLICY_LOOKUP_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)
POLICY_JSON_PARSE_ERRORS = (TypeError, ValueError, JSONDecodeError)
POLICY_RULE_VALIDATION_ERRORS = (ValidationError, ValueError, TypeError)


class PlannerRerankPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_policies(
        self,
        *,
        workspace_id: str,
        user_id: str,
        base_domain_id: Optional[int] = None,
        include_inactive: bool = False,
    ) -> Dict[str, Any]:
        domain_row = None
        if base_domain_id is not None:
            domain_row = self._load_domain_row(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=base_domain_id,
            )
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              id,
              policy_key,
              name,
              description,
              scope_type,
              scope_workspace_id,
              scope_base_domain_id,
              priority,
              is_active,
              stop_on_match,
              policy_json,
              created_at,
              updated_at
            FROM planner_rerank_policy
            WHERE (
              scope_type = 'global'
              OR (scope_type = 'workspace' AND scope_workspace_id = :workspace_id)
              OR (
                :base_domain_id IS NOT NULL
                AND scope_type = 'global_domain'
                AND scope_base_domain_id = :base_domain_id
              )
              OR (
                :base_domain_id IS NOT NULL
                AND scope_type = 'workspace_domain'
                AND scope_workspace_id = :workspace_id
                AND scope_base_domain_id = :base_domain_id
              )
            )
            {"AND is_active = 1" if not include_inactive else ""}
            """,
            {
                "workspace_id": str(workspace_id),
                "base_domain_id": int(base_domain_id) if base_domain_id is not None else None,
            },
        )
        policies: List[Dict[str, Any]] = []
        for row in rows:
            payload = _json_safe_mapping(dict(row))
            payload["scope_rank"] = _scope_rank(str(payload.get("scope_type") or ""))
            payload["is_inherited"] = bool(
                base_domain_id is not None
                and str(payload.get("scope_type") or "") not in {"workspace", "workspace_domain"}
            )
            payload["policy_json"] = _parse_policy_rule(payload.get("policy_json")).model_dump()
            policies.append(payload)
        policies.sort(
            key=lambda row: (
                -int(row.get("scope_rank") or 0),
                int(row.get("priority") or 100),
                int(row.get("id") or 0),
            )
        )
        return {
            "workspace_id": str(workspace_id),
            "base_domain_id": int(base_domain_id) if base_domain_id is not None else None,
            "domain_name": str((domain_row or {}).get("domain_name") or "").strip() or None,
            "can_edit": True,
            "policies": policies,
        }

    def get_applicable_policies(
        self,
        *,
        workspace_id: str,
        base_domain_id: int,
    ) -> List[Dict[str, Any]]:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  id,
                  policy_key,
                  name,
                  description,
                  scope_type,
                  scope_workspace_id,
                  scope_base_domain_id,
                  priority,
                  is_active,
                  stop_on_match,
                  policy_json
                FROM planner_rerank_policy
                WHERE is_active = 1
                  AND (
                    scope_type = 'global'
                    OR (scope_type = 'workspace' AND scope_workspace_id = :workspace_id)
                    OR (scope_type = 'global_domain' AND scope_base_domain_id = :base_domain_id)
                    OR (
                      scope_type = 'workspace_domain'
                      AND scope_workspace_id = :workspace_id
                      AND scope_base_domain_id = :base_domain_id
                    )
                  )
                """,
                {
                    "workspace_id": str(workspace_id),
                    "base_domain_id": int(base_domain_id),
                },
            )
        except POLICY_LOOKUP_FALLBACK_ERRORS as exc:  # pragma: no cover - defensive runtime fallback
            logger.warning(
                "planner rerank policy lookup failed workspace_id=%s base_domain_id=%s err=%s",
                workspace_id,
                base_domain_id,
                exc,
            )
            return []
        policies: List[Dict[str, Any]] = []
        for row in rows:
            payload = _json_safe_mapping(dict(row))
            try:
                payload["policy_json"] = _parse_policy_rule(payload.get("policy_json")).model_dump()
            except ForgeError:
                continue
            policies.append(payload)
        policies.sort(
            key=lambda row: (
                -_scope_rank(str(row.get("scope_type") or "")),
                int(row.get("priority") or 100),
                int(row.get("id") or 0),
            )
        )
        return policies

    def upsert_policy(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        payload: Any,
    ) -> Dict[str, Any]:
        req = PlannerRerankPolicyUpsertRequest.model_validate(payload)
        if req.scope_type.startswith("workspace") and (req.scope_workspace_id or workspace_id) != workspace_id:
            raise ForgeError("workspace scope must match the active workspace", status_code=400)
        if req.scope_base_domain_id is not None:
            self._load_domain_row(
                workspace_id=workspace_id,
                user_id=actor_user_id,
                domain_id=req.scope_base_domain_id,
            )
        params = {
            "policy_key": req.policy_key,
            "name": req.name,
            "description": req.description,
            "scope_type": req.scope_type,
            "scope_workspace_id": req.scope_workspace_id or (workspace_id if req.scope_type.startswith("workspace") else None),
            "scope_base_domain_id": req.scope_base_domain_id,
            "priority": int(req.priority),
            "is_active": 1 if req.is_active else 0,
            "stop_on_match": 1 if req.stop_on_match else 0,
            "policy_json": json.dumps(req.policy_json.model_dump()),
        }
        existing_row: Optional[Dict[str, Any]] = None
        if req.id is not None:
            existing_row = self._load_policy_row(policy_id=int(req.id), workspace_id=workspace_id)
            row_domain_id = existing_row.get("scope_base_domain_id")
            if row_domain_id is not None and int(row_domain_id) != int(req.scope_base_domain_id or 0):
                raise ForgeError("policy id does not belong to the requested scope_base_domain_id", status_code=400)
        else:
            existing = self._sql.execute_query_mappings(
                """
                SELECT id, policy_json
                FROM planner_rerank_policy
                WHERE policy_key = :policy_key
                  AND scope_type = :scope_type
                  AND (
                    (scope_workspace_id IS NULL AND :scope_workspace_id IS NULL)
                    OR scope_workspace_id = :scope_workspace_id
                  )
                  AND (
                    (scope_base_domain_id IS NULL AND :scope_base_domain_id IS NULL)
                    OR scope_base_domain_id = :scope_base_domain_id
                  )
                LIMIT 1
                """,
                params,
            )
            if existing:
                existing_row = dict(existing[0])
        with self._sql.transaction() as tx:
            if existing_row:
                row = existing_row
                tx.execute_write(
                    """
                    UPDATE planner_rerank_policy
                    SET policy_key = :policy_key,
                        name = :name,
                        description = :description,
                        scope_type = :scope_type,
                        scope_workspace_id = :scope_workspace_id,
                        scope_base_domain_id = :scope_base_domain_id,
                        priority = :priority,
                        is_active = :is_active,
                        stop_on_match = :stop_on_match,
                        policy_json = :policy_json,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :policy_id
                    """,
                    {**params, "policy_id": int(row["id"])},
                )
                tx.execute_write(
                    """
                    INSERT INTO planner_rerank_policy_audit (
                      policy_id,
                      action_type,
                      previous_policy_json,
                      new_policy_json,
                      actor_user_id
                    ) VALUES (
                      :policy_id,
                      'update',
                      :previous_policy_json,
                      :new_policy_json,
                      :actor_user_id
                    )
                    """,
                    {
                        "policy_id": int(row["id"]),
                        "previous_policy_json": row.get("policy_json"),
                        "new_policy_json": params["policy_json"],
                        "actor_user_id": str(actor_user_id),
                    },
                )
                policy_id = int(row["id"])
            else:
                insert_result = tx.execute_insert(
                    """
                    INSERT INTO planner_rerank_policy (
                      policy_key,
                      name,
                      description,
                      scope_type,
                      scope_workspace_id,
                      scope_base_domain_id,
                      priority,
                      is_active,
                      stop_on_match,
                      policy_json
                    ) VALUES (
                      :policy_key,
                      :name,
                      :description,
                      :scope_type,
                      :scope_workspace_id,
                      :scope_base_domain_id,
                      :priority,
                      :is_active,
                      :stop_on_match,
                      :policy_json
                    )
                    """,
                    params,
                )
                policy_id = int(getattr(insert_result, "lastrowid", 0) or 0)
                if policy_id <= 0:
                    rows = self._sql.execute_query_mappings(
                        """
                        SELECT id
                        FROM planner_rerank_policy
                        WHERE policy_key = :policy_key
                          AND scope_type = :scope_type
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    policy_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if policy_id <= 0:
                    raise ForgeError("Unable to resolve planner rerank policy id after insert.", status_code=500)
                if policy_id > 0:
                    tx.execute_write(
                        """
                        INSERT INTO planner_rerank_policy_audit (
                          policy_id,
                          action_type,
                          previous_policy_json,
                          new_policy_json,
                          actor_user_id
                        ) VALUES (
                          :policy_id,
                          'create',
                          NULL,
                          :new_policy_json,
                          :actor_user_id
                        )
                        """,
                        {
                            "policy_id": policy_id,
                            "new_policy_json": params["policy_json"],
                            "actor_user_id": str(actor_user_id),
                        },
                    )
        return {
            "policy_id": policy_id,
            "policy_key": req.policy_key,
            "scope_type": req.scope_type,
            "scope_workspace_id": params["scope_workspace_id"],
            "scope_base_domain_id": params["scope_base_domain_id"],
            "priority": req.priority,
            "is_active": req.is_active,
            "stop_on_match": req.stop_on_match,
            "policy_json": req.policy_json.model_dump(),
        }

    def delete_policy(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        policy_id: int,
    ) -> Dict[str, Any]:
        row = self._load_policy_row(policy_id=policy_id, workspace_id=workspace_id)
        scope_base_domain_id = row.get("scope_base_domain_id")
        if scope_base_domain_id is not None:
            self._load_domain_row(
                workspace_id=workspace_id,
                user_id=actor_user_id,
                domain_id=int(scope_base_domain_id),
            )
        deleted = self._sql.execute_write(
            "DELETE FROM planner_rerank_policy WHERE id = :policy_id",
            {"policy_id": int(policy_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner rerank policy not found", status_code=404)
        return {
            "deleted": True,
            "policy_id": int(policy_id),
        }

    def _load_domain_row(self, *, workspace_id: str, user_id: str, domain_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              d.name AS domain_name,
              udm.can_edit
            FROM domain d
            JOIN user_domain_mapping udm
              ON udm.domain_id = d.id
             AND udm.user_id = :user_id
             AND udm.can_read = 1
            WHERE d.workspace_id = :workspace_id
              AND d.id = :domain_id
              AND d.is_active = 1
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id),
                "user_id": str(user_id),
                "domain_id": int(domain_id),
            },
        )
        if not rows:
            raise ForgeError("Domain not found or access denied", status_code=404)
        return dict(rows[0])

    def _load_policy_row(self, *, policy_id: int, workspace_id: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              policy_key,
              name,
              description,
              scope_type,
              scope_workspace_id,
              scope_base_domain_id,
              priority,
              is_active,
              stop_on_match,
              policy_json
            FROM planner_rerank_policy
            WHERE id = :policy_id
              AND (
                scope_workspace_id IS NULL
                OR scope_workspace_id = :workspace_id
              )
            LIMIT 1
            """,
            {
                "policy_id": int(policy_id),
                "workspace_id": str(workspace_id),
            },
        )
        if not rows:
            raise ForgeError("Planner rerank policy not found", status_code=404)
        return dict(rows[0])


def _parse_policy_rule(value: Any) -> PlannerRerankPolicyRule:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except POLICY_JSON_PARSE_ERRORS as exc:  # pragma: no cover - defensive
            raise ForgeError(f"Invalid planner rerank policy JSON: {exc}", status_code=500)
    try:
        return PlannerRerankPolicyRule.model_validate(raw or {})
    except POLICY_RULE_VALIDATION_ERRORS as exc:
        raise ForgeError(f"Invalid planner rerank policy JSON: {exc}", status_code=500)


def _scope_rank(scope_type: str) -> int:
    token = str(scope_type or "").strip().lower()
    if token not in PLANNER_RERANK_SCOPE_TYPES:
        return 0
    return {
        "workspace_domain": 4,
        "workspace": 3,
        "global_domain": 2,
        "global": 1,
    }[token]


def _json_safe_mapping(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


__all__ = ["PlannerRerankPolicyService"]

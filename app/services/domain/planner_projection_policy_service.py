from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.planner_projection_policy import PlannerProjectionPolicyRule, PlannerProjectionPolicyUpsertRequest
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.policy_scope_service import (
    DOMAIN_POLICY_SCOPE_TYPES,
    annotate_effective_scoped_rows,
    require_supported_scope,
    scoped_query_predicate,
    sort_and_dedupe_scoped_policies,
)

logger = logging.getLogger(__name__)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "student_listing_identity_projection",
        "name": "Student listing identity projection",
        "description": "Ensure student identity concepts appear first for student listing prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_base_domain_id": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["student_listing"],
            "projection_mode": "prepend",
            "required_concept_keys": ["STUDENT_ID", "STUDENT_FIRST_NAME", "STUDENT_LAST_NAME"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_listing_school_context",
        "name": "Student listing school context",
        "description": "Require school filter and school join context for student listing prompts with a school literal.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_base_domain_id": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["student_listing", "school_literal_present"],
            "projection_mode": "prepend",
            "required_concept_keys": ["STUDENT_FIRST_NAME", "STUDENT_LAST_NAME"],
            "required_filter_concept_keys": ["SCHOOL_NAME"],
            "required_join_tables": ["dim_school"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "human_school_filter_projection",
        "name": "Human school filter projection",
        "description": "Prefer school-name semantics over technical school identifiers for school-filter prompts unless the prompt explicitly asks for a key or code.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_base_domain_id": None,
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["needs_school_filter"],
            "exclude_signals_any": ["explicit_school_key_request"],
            "projection_mode": "prepend",
            "required_concept_keys": ["SCHOOL_NAME"],
            "excluded_concept_keys": ["SCHOOL_ID"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "human_staff_role_filter_projection",
        "name": "Human staff role filter projection",
        "description": "Prefer human-readable staff role/title columns over staff classification when the prompt asks for a staff role and does not explicitly ask for classification values.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_base_domain_id": None,
        "priority": 130,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["staff_role_prompt"],
            "exclude_signals_any": ["explicit_staff_classification_request"],
            "projection_mode": "prepend",
            "required_concept_keys": ["STAFF_ROLE"],
            "excluded_concept_keys": ["STAFF_CLASSIFICATION"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_listing_projection",
        "name": "School listing projection",
        "description": "Ensure school listing prompts lead with human-readable school identity columns.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_base_domain_id": None,
        "priority": 140,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["school_listing"],
            "projection_mode": "prepend",
            "required_column_names": ["school_name", "lea_name", "school_number"],
        },
        "_seeded": True,
    },
)


class PlannerProjectionPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_projection_requirements(
        self,
        *,
        workspace_id: Optional[str],
        base_domain_id: Optional[int],
        prompt_signals: Sequence[str],
    ) -> Dict[str, Any]:
        signals = [str(item or "").strip() for item in prompt_signals if str(item or "").strip()]
        if not signals:
            return {
                "required_concept_keys": [],
                "excluded_concept_keys": [],
                "required_column_names": [],
                "excluded_column_names": [],
                "required_filter_concept_keys": [],
                "required_join_tables": [],
                "projection_mode": "prepend",
                "matched_policies": [],
            }

        policies = self.get_applicable_policies(
            workspace_id=workspace_id,
            base_domain_id=base_domain_id,
        )
        required_concept_keys: List[str] = []
        excluded_concept_keys: List[str] = []
        required_column_names: List[str] = []
        excluded_column_names: List[str] = []
        required_filter_concept_keys: List[str] = []
        required_join_tables: List[str] = []
        matched_policies: List[str] = []
        concept_seen: set[str] = set()
        excluded_concept_seen: set[str] = set()
        required_column_seen: set[str] = set()
        excluded_column_seen: set[str] = set()
        filter_concept_seen: set[str] = set()
        join_seen: set[str] = set()
        projection_mode = "prepend"

        for row in policies:
            rule = _parse_policy_rule(row.get("policy_json"))
            if not _rule_matches(rule=rule, prompt_signals=signals):
                continue
            matched_policies.append(str(row.get("policy_key") or ""))
            if rule.projection_mode == "prepend":
                projection_mode = "prepend"
            elif projection_mode != "prepend":
                projection_mode = rule.projection_mode
            for concept_key in rule.required_concept_keys:
                if concept_key in concept_seen:
                    continue
                concept_seen.add(concept_key)
                required_concept_keys.append(concept_key)
            for concept_key in rule.excluded_concept_keys:
                if concept_key in excluded_concept_seen:
                    continue
                excluded_concept_seen.add(concept_key)
                excluded_concept_keys.append(concept_key)
            for column_name in rule.required_column_names:
                if column_name in required_column_seen:
                    continue
                required_column_seen.add(column_name)
                required_column_names.append(column_name)
            for column_name in rule.excluded_column_names:
                if column_name in excluded_column_seen:
                    continue
                excluded_column_seen.add(column_name)
                excluded_column_names.append(column_name)
            for concept_key in rule.required_filter_concept_keys:
                if concept_key in filter_concept_seen:
                    continue
                filter_concept_seen.add(concept_key)
                required_filter_concept_keys.append(concept_key)
            for table_name in rule.required_join_tables:
                if table_name in join_seen:
                    continue
                join_seen.add(table_name)
                required_join_tables.append(table_name)
            if bool(row.get("stop_on_match")):
                break

        return {
            "required_concept_keys": required_concept_keys,
            "excluded_concept_keys": excluded_concept_keys,
            "required_column_names": required_column_names,
            "excluded_column_names": excluded_column_names,
            "required_filter_concept_keys": required_filter_concept_keys,
            "required_join_tables": required_join_tables,
            "projection_mode": projection_mode,
            "matched_policies": [item for item in matched_policies if item],
        }

    def get_applicable_policies(
        self,
        *,
        workspace_id: Optional[str],
        base_domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = [dict(item) for item in _SEED_POLICIES]
        try:
            db_rows = self._sql.execute_query_mappings(
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
                  policy_json
                FROM planner_projection_policy
                WHERE is_active = 1
                  AND {scoped_query_predicate(include_base_domain=True)}
                """,
                {
                    "workspace_id": str(workspace_id or "").strip() or None,
                    "base_domain_id": int(base_domain_id) if base_domain_id is not None else None,
                },
            )
        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:  # pragma: no cover - defensive runtime fallback
            logger.warning(
                "planner projection policy lookup failed workspace_id=%s err=%s",
                workspace_id,
                exc,
            )
            db_rows = []

        rows.extend({**dict(row), "_seeded": False} for row in db_rows)
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            try:
                payload["policy_json"] = _parse_policy_rule(payload.get("policy_json")).model_dump()
            except (TypeError, ValueError, ValidationError):
                continue
            normalized.append(payload)

        return sort_and_dedupe_scoped_policies(normalized)

    def list_policies(
        self,
        *,
        workspace_id: str,
        base_domain_id: Optional[int] = None,
        include_inactive: bool = False,
        include_seeded: bool = True,
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        if include_seeded:
            rows.extend({**dict(item), "_seeded": True} for item in _SEED_POLICIES)
        db_rows = self._sql.execute_query_mappings(
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
            FROM planner_projection_policy
            WHERE {scoped_query_predicate(include_base_domain=True)}
            {"AND is_active = 1" if not include_inactive else ""}
            """,
            {
                "workspace_id": str(workspace_id),
                "base_domain_id": int(base_domain_id) if base_domain_id is not None else None,
            },
        )
        rows.extend({**dict(row), "_seeded": False} for row in db_rows)

        policies: List[Dict[str, Any]] = []
        for row in rows:
            payload = _json_safe_mapping(dict(row))
            payload["policy_json"] = _parse_policy_rule(payload.get("policy_json")).model_dump()
            payload["is_seeded"] = bool(payload.get("_seeded"))
            payload["can_edit"] = not payload["is_seeded"]
            payload["can_delete"] = not payload["is_seeded"]
            policies.append(payload)

        policies = annotate_effective_scoped_rows(policies)

        return {
            "workspace_id": str(workspace_id),
            "base_domain_id": int(base_domain_id) if base_domain_id is not None else None,
            "can_edit": True,
            "policies": policies,
        }

    def upsert_policy(
        self,
        *,
        workspace_id: str,
        payload: Any,
    ) -> Dict[str, Any]:
        req = PlannerProjectionPolicyUpsertRequest.model_validate(payload)
        scope_type = require_supported_scope(
            scope_type=req.scope_type,
            allowed_scope_types=DOMAIN_POLICY_SCOPE_TYPES,
            family_label="planner projection policies",
        )
        if scope_type.startswith("workspace") and (req.scope_workspace_id or workspace_id) != workspace_id:
            raise ForgeError("workspace scope must match the active workspace", status_code=400)
        if req.scope_base_domain_id is not None:
            self._load_domain_row(workspace_id=workspace_id, domain_id=req.scope_base_domain_id)
        params = {
            "policy_key": req.policy_key,
            "name": req.name,
            "description": req.description,
            "scope_type": scope_type,
            "scope_workspace_id": req.scope_workspace_id or (workspace_id if scope_type.startswith("workspace") else None),
            "scope_base_domain_id": req.scope_base_domain_id if "domain" in scope_type else None,
            "priority": int(req.priority),
            "is_active": 1 if req.is_active else 0,
            "stop_on_match": 1 if req.stop_on_match else 0,
            "policy_json": json.dumps(req.policy_json.model_dump()),
        }
        existing_row: Optional[Dict[str, Any]] = None
        if req.id is not None:
            existing_row = self._load_policy_row(policy_id=int(req.id), workspace_id=workspace_id)
        else:
            existing = self._sql.execute_query_mappings(
                """
                SELECT id
                FROM planner_projection_policy
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
                policy_id = int(existing_row["id"])
                tx.execute_write(
                    """
                    UPDATE planner_projection_policy
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
                    {**params, "policy_id": policy_id},
                )
            else:
                insert_result = tx.execute_insert(
                    """
                    INSERT INTO planner_projection_policy (
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
                        FROM planner_projection_policy
                        WHERE policy_key = :policy_key
                          AND scope_type = :scope_type
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    policy_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if policy_id <= 0:
                    raise ForgeError("Unable to resolve planner projection policy id after insert.", status_code=500)

        row = self._load_policy_row(policy_id=policy_id, workspace_id=workspace_id)
        payload_out = _json_safe_mapping(row)
        payload_out["policy_json"] = _parse_policy_rule(payload_out.get("policy_json")).model_dump()
        payload_out["is_seeded"] = False
        payload_out["can_edit"] = True
        payload_out["can_delete"] = True
        return payload_out

    def delete_policy(
        self,
        *,
        workspace_id: str,
        policy_id: int,
    ) -> Dict[str, Any]:
        row = self._load_policy_row(policy_id=policy_id, workspace_id=workspace_id)
        scope_base_domain_id = row.get("scope_base_domain_id")
        if scope_base_domain_id is not None:
            self._load_domain_row(workspace_id=workspace_id, domain_id=int(scope_base_domain_id))
        deleted = self._sql.execute_write(
            "DELETE FROM planner_projection_policy WHERE id = :policy_id",
            {"policy_id": int(policy_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner projection policy not found", status_code=404)
        return {
            "deleted": True,
            "policy_id": int(policy_id),
            "policy_key": str(row.get("policy_key") or ""),
        }

    def _load_domain_row(self, *, workspace_id: str, domain_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              d.name AS domain_name
            FROM domain d
            WHERE d.workspace_id = :workspace_id
              AND d.id = :domain_id
              AND d.is_active = 1
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id),
                "domain_id": int(domain_id),
            },
        )
        if not rows:
            raise ForgeError("Domain not found", status_code=404)
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
              policy_json,
              created_at,
              updated_at
            FROM planner_projection_policy
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
            raise ForgeError("Planner projection policy not found", status_code=404)
        return dict(rows[0])


def _parse_policy_rule(value: Any) -> PlannerProjectionPolicyRule:
    if isinstance(value, PlannerProjectionPolicyRule):
        return value
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("Invalid planner projection policy payload")
    return PlannerProjectionPolicyRule.model_validate(dict(value))


def _rule_matches(*, rule: PlannerProjectionPolicyRule, prompt_signals: Sequence[str]) -> bool:
    signal_set = {str(item or "").strip() for item in prompt_signals if str(item or "").strip()}
    if rule.when_signals_all and any(item not in signal_set for item in rule.when_signals_all):
        return False
    if rule.when_signals_any and not any(item in signal_set for item in rule.when_signals_any):
        return False
    if rule.exclude_signals_any and any(item in signal_set for item in rule.exclude_signals_any):
        return False
    return True

def _json_safe_mapping(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value

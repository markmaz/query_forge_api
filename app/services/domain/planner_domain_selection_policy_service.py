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
from app.models.domain.planner_domain_selection_policy import (
    PlannerDomainSelectionPolicyRule,
    PlannerDomainSelectionPolicyUpsertRequest,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.policy_scope_service import (
    annotate_effective_rows,
    global_workspace_query_predicate,
    require_global_workspace_scope,
    sort_and_dedupe_global_workspace_policies,
)

logger = logging.getLogger(__name__)

POLICY_LOOKUP_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)
POLICY_RULE_VALIDATION_ERRORS = (ValidationError, ValueError, TypeError)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "subgroup_shortlist_selection_boost",
        "name": "Subgroup shortlist selection boost",
        "description": "Boost domains whose shortlist already includes subgroup columns for subgroup prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["subgroup_prompt"],
            "required_shortlist_features": ["SUBGROUP_COLUMN"],
            "score_delta": 0.15,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_identity_listing_selection_boost",
        "name": "Student identity listing selection boost",
        "description": "Boost domains whose shortlist contains student identity columns for student listing prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["student_listing"],
            "required_shortlist_features": ["STUDENT_IDENTITY_COLUMN"],
            "score_delta": 0.08,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_work_identity_selection_boost",
        "name": "Staff work identity selection boost",
        "description": "Boost domains whose shortlist contains staff identity columns for staff work-context prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["staff_work_context_prompt"],
            "required_shortlist_features": ["STAFF_IDENTITY_COLUMN"],
            "score_delta": 0.14,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_school_identity_selection_boost",
        "name": "Student school identity selection boost",
        "description": "Boost domains whose shortlist contains student identity columns for student-school prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 130,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["student_school_context_prompt"],
            "required_shortlist_features": ["STUDENT_IDENTITY_COLUMN"],
            "score_delta": 0.12,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "adm_signal_column_selection_boost",
        "name": "ADM signal column selection boost",
        "description": "Boost domains whose shortlist contains ADM signal columns for ADM prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 140,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["adm_prompt"],
            "required_shortlist_features": ["ADM_SIGNAL_COLUMN"],
            "score_delta": 0.2,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "adm_metric_selection_boost",
        "name": "ADM metric selection boost",
        "description": "Boost domains whose capabilities include ADM metrics for ADM prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 150,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["adm_prompt"],
            "required_capability_features": ["ADM_METRIC"],
            "score_delta": 0.12,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "age_extreme_birth_date_selection_boost",
        "name": "Age extreme birth date selection boost",
        "description": "Boost domains whose shortlist contains birth-date columns for age-extreme prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 160,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["age_extreme_prompt"],
            "required_shortlist_features": ["BIRTH_DATE_COLUMN"],
            "score_delta": 0.2,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "age_extreme_age_selection_boost",
        "name": "Age extreme age selection boost",
        "description": "Boost domains whose shortlist contains age columns for age-extreme prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 170,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["age_extreme_prompt"],
            "required_shortlist_features": ["AGE_COLUMN"],
            "score_delta": 0.16,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "birth_month_birth_date_selection_boost",
        "name": "Birth month birth date selection boost",
        "description": "Boost domains whose shortlist contains birth-date columns for birth-month prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 180,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["birth_month_prompt"],
            "required_shortlist_features": ["BIRTH_DATE_COLUMN"],
            "score_delta": 0.24,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "calendar_day_selection_boost",
        "name": "Calendar day selection boost",
        "description": "Boost domains whose shortlist contains calendar-day columns for days-off prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 190,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["calendar_days_off_prompt"],
            "required_shortlist_features": ["CALENDAR_DAY_COLUMN"],
            "score_delta": 0.16,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_day_flag_selection_boost",
        "name": "School day flag selection boost",
        "description": "Boost domains whose shortlist contains school-day flags for days-off prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 200,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["calendar_days_off_prompt"],
            "required_shortlist_features": ["SCHOOL_DAY_FLAG_COLUMN"],
            "score_delta": 0.18,
        },
        "_seeded": True,
    },
)


class PlannerDomainSelectionPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def score_adjustment(
        self,
        *,
        workspace_id: Optional[str],
        vertical_norm: Optional[str],
        prompt_signals: Sequence[str],
        shortlist_features: Sequence[str],
        capability_features: Sequence[str],
    ) -> float:
        policies = self.get_applicable_policies(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
        )
        signal_set = set(_normalized_tokens(prompt_signals))
        shortlist_set = set(_normalized_tokens(shortlist_features, upper=True))
        capability_set = set(_normalized_tokens(capability_features, upper=True))

        total = 0.0
        for row in policies:
            rule = _parse_policy_rule(row.get("policy_json"))
            if not _rule_matches(
                rule=rule,
                prompt_signals=signal_set,
                shortlist_features=shortlist_set,
                capability_features=capability_set,
            ):
                continue
            total += float(rule.score_delta or 0.0)
            if bool(row.get("stop_on_match")):
                break
        return round(total, 5)

    def get_applicable_policies(
        self,
        *,
        workspace_id: Optional[str],
        vertical_norm: Optional[str],
    ) -> List[Dict[str, Any]]:
        del vertical_norm
        rows: List[Dict[str, Any]] = [dict(item) for item in _SEED_POLICIES]
        if self._enable_db_lookup:
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
                      scope_vertical_norm,
                      priority,
                      is_active,
                      stop_on_match,
                      policy_json
                    FROM planner_domain_selection_policy
                    WHERE is_active = 1
                      AND {global_workspace_query_predicate()}
                    """,
                    {
                        "workspace_id": str(workspace_id or "").strip(),
                    },
                )
                rows.extend(dict(item) for item in db_rows)
            except POLICY_LOOKUP_FALLBACK_ERRORS as exc:  # pragma: no cover
                logger.warning(
                    "planner domain selection policy lookup failed workspace_id=%s err=%s",
                    workspace_id,
                    exc,
                )

        policies: List[Dict[str, Any]] = []
        for row in sort_and_dedupe_global_workspace_policies(rows):
            payload = dict(row)
            try:
                payload["policy_json"] = _parse_policy_rule(payload.get("policy_json")).model_dump()
            except POLICY_RULE_VALIDATION_ERRORS:
                continue
            policies.append(payload)
        policies.sort(key=lambda row: (int(row.get("priority") or 100), int(row.get("id") or 0)))
        return policies

    def list_policies(
        self,
        *,
        workspace_id: str,
        include_inactive: bool = False,
        include_seeded: bool = True,
    ) -> Dict[str, Any]:
        rows: list[dict[str, Any]] = []
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
              scope_vertical_norm,
              priority,
              is_active,
              stop_on_match,
              policy_json,
              created_at,
              updated_at
            FROM planner_domain_selection_policy
            WHERE {global_workspace_query_predicate()}
            {"AND is_active = 1" if not include_inactive else ""}
            """,
            {"workspace_id": str(workspace_id)},
        )
        rows.extend({**dict(row), "_seeded": False} for row in db_rows)

        policies: list[dict[str, Any]] = []
        for row in rows:
            payload = _json_safe_mapping(dict(row))
            payload["policy_json"] = _parse_policy_rule(payload.get("policy_json")).model_dump()
            payload["is_seeded"] = bool(payload.get("_seeded"))
            payload["can_edit"] = not payload["is_seeded"]
            payload["can_delete"] = not payload["is_seeded"]
            policies.append(payload)

        return {
            "workspace_id": str(workspace_id),
            "can_edit": True,
            "policies": annotate_effective_rows(policies),
        }

    def upsert_policy(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        payload: Any,
    ) -> Dict[str, Any]:
        del actor_user_id
        req = PlannerDomainSelectionPolicyUpsertRequest.model_validate(payload)
        scope_type = require_global_workspace_scope(scope_type=req.scope_type)
        if scope_type == "workspace" and (req.scope_workspace_id or workspace_id) != workspace_id:
            raise ForgeError("workspace scope must match the active workspace", status_code=400)
        params = {
            "policy_key": req.policy_key,
            "name": req.name,
            "description": req.description,
            "scope_type": scope_type,
            "scope_workspace_id": req.scope_workspace_id or (workspace_id if scope_type == "workspace" else None),
            "scope_vertical_norm": None,
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
                FROM planner_domain_selection_policy
                WHERE policy_key = :policy_key
                  AND scope_type = :scope_type
                  AND (
                    (scope_workspace_id IS NULL AND :scope_workspace_id IS NULL)
                    OR scope_workspace_id = :scope_workspace_id
                  )
                  AND (
                    (scope_vertical_norm IS NULL AND :scope_vertical_norm IS NULL)
                    OR scope_vertical_norm = :scope_vertical_norm
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
                    UPDATE planner_domain_selection_policy
                    SET policy_key = :policy_key,
                        name = :name,
                        description = :description,
                        scope_type = :scope_type,
                        scope_workspace_id = :scope_workspace_id,
                        scope_vertical_norm = :scope_vertical_norm,
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
                    INSERT INTO planner_domain_selection_policy (
                      policy_key,
                      name,
                      description,
                      scope_type,
                      scope_workspace_id,
                      scope_vertical_norm,
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
                      :scope_vertical_norm,
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
                        FROM planner_domain_selection_policy
                        WHERE policy_key = :policy_key
                          AND scope_type = :scope_type
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    policy_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if policy_id <= 0:
                    raise ForgeError("Unable to resolve planner domain selection policy id after insert.", status_code=500)

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
        actor_user_id: str,
        policy_id: int,
    ) -> Dict[str, Any]:
        del actor_user_id
        row = self._load_policy_row(policy_id=policy_id, workspace_id=workspace_id)
        deleted = self._sql.execute_write(
            "DELETE FROM planner_domain_selection_policy WHERE id = :policy_id",
            {"policy_id": int(policy_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner domain selection policy not found", status_code=404)
        return {"deleted": True, "policy_id": int(policy_id), "policy_key": str(row.get("policy_key") or "")}

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
              scope_vertical_norm,
              priority,
              is_active,
              stop_on_match,
              policy_json,
              created_at,
              updated_at
            FROM planner_domain_selection_policy
            WHERE id = :policy_id
              AND (
                scope_workspace_id IS NULL
                OR scope_workspace_id = :workspace_id
              )
            LIMIT 1
            """,
            {"policy_id": int(policy_id), "workspace_id": str(workspace_id)},
        )
        if not rows:
            raise ForgeError("Planner domain selection policy not found", status_code=404)
        return dict(rows[0])


def _parse_policy_rule(value: Any) -> PlannerDomainSelectionPolicyRule:
    if isinstance(value, PlannerDomainSelectionPolicyRule):
        return value
    if isinstance(value, str):
        return PlannerDomainSelectionPolicyRule.model_validate_json(value)
    return PlannerDomainSelectionPolicyRule.model_validate(value or {})


def _normalized_tokens(values: Sequence[str], *, upper: bool = False) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        if upper:
            token = token.upper()
        if token not in out:
            out.append(token)
    return out


def _rule_matches(
    *,
    rule: PlannerDomainSelectionPolicyRule,
    prompt_signals: Sequence[str],
    shortlist_features: Sequence[str],
    capability_features: Sequence[str],
) -> bool:
    signal_set = set(_normalized_tokens(prompt_signals))
    shortlist_set = set(_normalized_tokens(shortlist_features, upper=True))
    capability_set = set(_normalized_tokens(capability_features, upper=True))

    if rule.when_signals_all and any(signal not in signal_set for signal in rule.when_signals_all):
        return False
    if rule.when_signals_any and not any(signal in signal_set for signal in rule.when_signals_any):
        return False
    if rule.exclude_signals_any and any(signal in signal_set for signal in rule.exclude_signals_any):
        return False
    if rule.required_shortlist_features and any(feature not in shortlist_set for feature in rule.required_shortlist_features):
        return False
    if rule.required_capability_features and any(feature not in capability_set for feature in rule.required_capability_features):
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

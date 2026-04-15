from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.models.domain.planner_semantic_join_policy import (
    PlannerSemanticJoinPolicyRule,
    PlannerSemanticJoinPreferenceStep,
)
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)
POLICY_LOOKUP_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "school_name_filter_column_preference",
        "name": "School name filter column preference",
        "description": "Prefer canonical school-name columns before fact-table copies for school-name filters.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "filter_column_preference",
            "when_filter_concept_keys_any": ["SCHOOL_NAME", "STUDENT_SCHOOL_NAME"],
            "preference_steps": [
                {"table_names": ["dim_school"], "column_names": ["school_name"]},
                {"table_prefixes": ["fct_student_"], "column_contains": ["school_name"]},
                {"column_contains": ["school_name"]},
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_school_required_join",
        "name": "Student school required join",
        "description": "Inject the school dimension join when student projections use a school-name filter.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 200,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "required_join",
            "when_filter_concept_keys_any": ["SCHOOL_NAME", "STUDENT_SCHOOL_NAME"],
            "when_selected_tables_all": ["dim_student"],
            "when_required_join_tables_any": ["dim_school"],
            "join_table": "dim_school",
            "join_on_concept_key": "SCHOOL_ID",
            "primary_table": "dim_student",
        },
        "_seeded": True,
    },
)


class PlannerSemanticJoinPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def filter_column_rank(self, *, concept_key: str, row: Dict[str, Any]) -> Tuple[int, int, float, int]:
        preference = 5
        rule = self._match_filter_rule(concept_key=concept_key)
        if rule is not None:
            steps = list(rule.preference_steps or [])
            preference = len(steps) + 1
            table_name = str(row.get("table_name") or "").strip().lower()
            column_name = str(row.get("column_name") or "").strip().lower()
            for idx, step in enumerate(steps):
                if _matches_preference_step(step=step, table_name=table_name, column_name=column_name):
                    preference = idx
                    break

        is_selected = 0 if bool(row.get("__selected__")) else 1
        score = -(_to_float(row.get("effective_weight")) or _to_float(row.get("final_score")) or 0.0)
        model_column_id = _to_int(row.get("model_column_id")) or 0
        return preference, is_selected, score, model_column_id

    def ensure_required_join_plan(
        self,
        *,
        join_plan: Any,
        selected_tables: Sequence[str],
        present_filter_concept_keys: Sequence[str],
        required_join_tables: Sequence[str],
    ) -> Dict[str, Any]:
        current = dict(join_plan) if isinstance(join_plan, dict) else {}
        if not required_join_tables:
            return current

        selected_table_set = {str(item or "").strip().lower() for item in selected_tables if str(item or "").strip()}
        filter_concept_set = {str(item or "").strip().upper() for item in present_filter_concept_keys if str(item or "").strip()}
        required_join_set = {str(item or "").strip().lower() for item in required_join_tables if str(item or "").strip()}

        joins = list(current.get("joins") or [])
        for row in self.get_applicable_policies():
            rule = _parse_policy_rule(row.get("policy_json"))
            if rule.action_key != "required_join":
                continue
            if rule.when_selected_tables_all and not set(rule.when_selected_tables_all).issubset(selected_table_set):
                continue
            if rule.when_filter_concept_keys_any and filter_concept_set.isdisjoint(set(rule.when_filter_concept_keys_any)):
                continue
            if rule.when_required_join_tables_any and required_join_set.isdisjoint(set(rule.when_required_join_tables_any)):
                continue

            join_table = str(rule.join_table or "").strip().lower()
            if not join_table:
                continue
            if any(str(item.get("table") or "").strip().lower() == join_table for item in joins if isinstance(item, dict)):
                continue

            joins.append(
                {
                    "table": join_table,
                    "on": [{"concept_key": str(rule.join_on_concept_key or "").strip().upper(), "op": "=", "value": str(rule.join_on_concept_key or "").strip().upper()}],
                }
            )
            if rule.primary_table and not str(current.get("primary_table") or "").strip():
                current["primary_table"] = rule.primary_table
            if bool(row.get("stop_on_match")):
                break

        if joins:
            current["joins"] = joins
        return current

    def get_applicable_policies(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = [dict(item) for item in _SEED_POLICIES]
        if not self._enable_db_lookup:
            return rows
        try:
            db_rows = self._sql.execute_query_mappings(
                """
                SELECT
                  id,
                  policy_key,
                  name,
                  description,
                  scope_type,
                  scope_workspace_id,
                  priority,
                  is_active,
                  stop_on_match,
                  policy_json
                FROM planner_semantic_join_policy
                WHERE is_active = 1
                ORDER BY priority ASC, id ASC
                """,
                {},
            )
        except POLICY_LOOKUP_FALLBACK_ERRORS:
            logger.exception("Failed to load planner semantic join policies from db")
            return rows

        for db_row in db_rows:
            row = dict(db_row)
            row["policy_json"] = _coerce_json_dict(row.get("policy_json"))
            rows.append(row)
        return sorted(rows, key=lambda item: (int(item.get("priority") or 100), int(item.get("id") or 0)))

    def _match_filter_rule(self, *, concept_key: str) -> Optional[PlannerSemanticJoinPolicyRule]:
        token = str(concept_key or "").strip().upper()
        if not token:
            return None
        for row in self.get_applicable_policies():
            rule = _parse_policy_rule(row.get("policy_json"))
            if rule.action_key != "filter_column_preference":
                continue
            if token in set(rule.when_filter_concept_keys_any):
                return rule
        return None


def _matches_preference_step(
    *,
    step: PlannerSemanticJoinPreferenceStep,
    table_name: str,
    column_name: str,
) -> bool:
    if step.table_names and table_name not in set(step.table_names):
        return False
    if step.table_prefixes and not any(table_name.startswith(prefix) for prefix in step.table_prefixes):
        return False
    if step.column_names and column_name not in set(step.column_names):
        return False
    if step.column_contains and not any(fragment in column_name for fragment in step.column_contains):
        return False
    return True


def _parse_policy_rule(value: Any) -> PlannerSemanticJoinPolicyRule:
    if isinstance(value, PlannerSemanticJoinPolicyRule):
        return value
    return PlannerSemanticJoinPolicyRule.model_validate(_coerce_json_dict(value))


def _coerce_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("policy_json must decode to an object")
        return dict(parsed)
    raise ValueError("policy_json must be an object")


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["PlannerSemanticJoinPolicyService"]

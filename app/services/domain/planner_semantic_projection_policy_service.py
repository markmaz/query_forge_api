from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.models.domain.planner_semantic_projection_policy import PlannerSemanticProjectionPolicyRule
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)
POLICY_LOOKUP_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "student_default_projection",
        "name": "Student default projection",
        "description": "Default student projection columns for semantic planner fallback projection.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "default_projection",
            "when_entity": "student",
            "projection_concept_keys": ["STUDENT_ID", "STUDENT_FIRST_NAME", "FIRST_NAME", "STUDENT_LAST_NAME", "LAST_NAME"],
            "preferred_table_names": ["dim_student"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_default_projection",
        "name": "Staff default projection",
        "description": "Default staff projection columns for semantic planner fallback projection.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "default_projection",
            "when_entity": "staff",
            "projection_concept_keys": ["STAFF_ID", "STAFF_FIRST_NAME", "FIRST_NAME", "STAFF_LAST_NAME", "LAST_NAME"],
            "preferred_table_names": ["dim_staff"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "parent_default_projection",
        "name": "Parent default projection",
        "description": "Default parent projection columns for semantic planner fallback projection.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "default_projection",
            "when_entity": "parent",
            "projection_concept_keys": ["PARENT_ID", "PARENT_FIRST_NAME", "FIRST_NAME", "PARENT_LAST_NAME", "LAST_NAME"],
            "preferred_table_names": ["dim_parent"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_name_filter_concepts",
        "name": "Student name filter concepts",
        "description": "Preferred concept order for student literal-name filters.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 200,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "name_filter_concepts",
            "when_entity": "student",
            "projection_concept_keys": ["STUDENT_LAST_NAME", "LAST_NAME", "STUDENT_FIRST_NAME", "FIRST_NAME"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_name_filter_concepts",
        "name": "Staff name filter concepts",
        "description": "Preferred concept order for staff literal-name filters.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 210,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "name_filter_concepts",
            "when_entity": "staff",
            "projection_concept_keys": ["STAFF_LAST_NAME", "LAST_NAME", "STAFF_FIRST_NAME", "FIRST_NAME"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "parent_name_filter_concepts",
        "name": "Parent name filter concepts",
        "description": "Preferred concept order for parent literal-name filters.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 220,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "name_filter_concepts",
            "when_entity": "parent",
            "projection_concept_keys": ["PARENT_LAST_NAME", "LAST_NAME", "PARENT_FIRST_NAME", "FIRST_NAME"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_id_concept_family",
        "name": "Student id concept family",
        "description": "Allow generic id columns to satisfy student-id requirements.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 300,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "concept_family", "when_concept_key": "STUDENT_ID", "concept_family": ["STUDENT_ID", "ID"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_first_name_concept_family",
        "name": "Student first-name concept family",
        "description": "Allow generic first-name columns to satisfy student first-name requirements.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 310,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "concept_family", "when_concept_key": "STUDENT_FIRST_NAME", "concept_family": ["STUDENT_FIRST_NAME", "FIRST_NAME"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_last_name_concept_family",
        "name": "Student last-name concept family",
        "description": "Allow generic last-name columns to satisfy student last-name requirements.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 320,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "concept_family", "when_concept_key": "STUDENT_LAST_NAME", "concept_family": ["STUDENT_LAST_NAME", "LAST_NAME"]},
        "_seeded": True,
    },
)


class PlannerSemanticProjectionPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def default_projection_concepts(self, *, entity: str) -> list[str]:
        rule = self._rule_for_entity(action_key="default_projection", entity=entity)
        return list(rule.projection_concept_keys or []) if rule else []

    def preferred_projection_tables(self, *, entity: str) -> list[str]:
        rule = self._rule_for_entity(action_key="default_projection", entity=entity)
        return list(rule.preferred_table_names or []) if rule else []

    def name_filter_concepts(self, *, entity: str) -> list[str]:
        rule = self._rule_for_entity(action_key="name_filter_concepts", entity=entity)
        return list(rule.projection_concept_keys or []) if rule else []

    def concept_family(self, *, concept_key: str) -> tuple[str, ...]:
        token = str(concept_key or "").strip().upper()
        if not token:
            return tuple()
        for row in self.get_applicable_policies():
            rule = _parse_policy_rule(row.get("policy_json"))
            if rule.action_key == "concept_family" and rule.when_concept_key == token:
                return tuple(rule.concept_family or [token])
        return (token,)

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
                FROM planner_semantic_projection_policy
                WHERE is_active = 1
                ORDER BY priority ASC, id ASC
                """,
                {},
            )
        except POLICY_LOOKUP_FALLBACK_ERRORS:
            logger.exception("Failed to load planner semantic projection policies from db")
            return rows
        for db_row in db_rows:
            row = dict(db_row)
            row["policy_json"] = _coerce_json_dict(row.get("policy_json"))
            rows.append(row)
        return sorted(rows, key=lambda item: (int(item.get("priority") or 100), int(item.get("id") or 0)))

    def _rule_for_entity(self, *, action_key: str, entity: str) -> Optional[PlannerSemanticProjectionPolicyRule]:
        normalized = str(entity or "").strip().lower()
        if not normalized:
            return None
        for row in self.get_applicable_policies():
            rule = _parse_policy_rule(row.get("policy_json"))
            if rule.action_key == action_key and rule.when_entity == normalized:
                return rule
        return None


def _parse_policy_rule(value: Any) -> PlannerSemanticProjectionPolicyRule:
    if isinstance(value, PlannerSemanticProjectionPolicyRule):
        return value
    return PlannerSemanticProjectionPolicyRule.model_validate(_coerce_json_dict(value))


def _coerce_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("policy_json must decode to an object")
        return dict(parsed)
    raise ValueError("policy_json must be an object")


__all__ = ["PlannerSemanticProjectionPolicyService"]

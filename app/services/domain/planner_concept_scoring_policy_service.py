from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.models.domain.planner_concept_scoring_policy import PlannerConceptScoringPolicyRule
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)
POLICY_LOOKUP_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "entity_exact_match_multiplier",
        "name": "Entity exact match multiplier",
        "description": "Boost concepts whose semantic entity matches the inferred intent entity.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["entity_exact_match"], "action_key": "entity_exact_match_multiplier", "factor_value": 1.4},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "entity_mismatch_multiplier",
        "name": "Entity mismatch multiplier",
        "description": "Downrank concepts whose semantic entity conflicts with the inferred intent entity.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["entity_mismatch"], "action_key": "entity_mismatch_multiplier", "factor_value": 0.7},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_entity_name_exact_multiplier",
        "name": "Student entity exact name multiplier",
        "description": "Prefer student-scoped name concepts for student intents.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["intent_student", "student_entity_name_exact"], "action_key": "student_entity_name_exact_multiplier", "factor_value": 1.6},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_entity_generic_name_multiplier",
        "name": "Student generic name multiplier",
        "description": "Slightly downrank generic name concepts for student intents.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 130,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["intent_student", "generic_name_concept"], "action_key": "student_entity_generic_name_multiplier", "factor_value": 0.85},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_cross_entity_name_multiplier",
        "name": "Student cross-entity name penalty",
        "description": "Downrank staff or parent name concepts when the intent stays student-scoped.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 135,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_context_all": ["intent_student"],
            "when_context_any": ["staff_name_concept", "parent_name_concept"],
            "action_key": "student_cross_entity_name_multiplier",
            "factor_value": 0.5,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_subject_staff_name_multiplier",
        "name": "Student intent staff-name penalty",
        "description": "Downrank staff name concepts for student subject prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 140,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["subject_student", "staff_name_concept"], "action_key": "student_subject_staff_name_multiplier", "factor_value": 0.55},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_subject_parent_name_multiplier",
        "name": "Student intent parent-name penalty",
        "description": "Downrank parent name concepts for student subject prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 150,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["subject_student", "parent_name_concept"], "action_key": "student_subject_parent_name_multiplier", "factor_value": 0.55},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_or_parent_subject_student_name_multiplier",
        "name": "Staff or parent subject student-name penalty",
        "description": "Downrank student name concepts for staff or parent subject prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 160,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_any": ["subject_staff", "subject_parent"], "action_key": "staff_or_parent_subject_student_name_multiplier", "factor_value": 0.6},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "name_slot_student_name_multiplier",
        "name": "Name slot student-name boost",
        "description": "Boost student-scoped name concepts when a name slot is present.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 170,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["has_name_slot", "subject_student", "student_name_concept"], "action_key": "name_slot_student_name_multiplier", "factor_value": 1.3},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "name_slot_generic_name_multiplier",
        "name": "Name slot generic-name boost",
        "description": "Slightly boost generic name concepts when a name slot is present.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 180,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["has_name_slot", "generic_name_concept"], "action_key": "name_slot_generic_name_multiplier", "factor_value": 1.1},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_slot_multiplier",
        "name": "School slot boost",
        "description": "Boost school and district concepts when a school slot is present.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 190,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["has_school_slot", "school_slot_match"], "action_key": "school_slot_multiplier", "factor_value": 1.25},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "district_slot_multiplier",
        "name": "District slot boost",
        "description": "Boost district concepts when a district slot is present.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 200,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["has_district_slot", "district_slot_match"], "action_key": "district_slot_multiplier", "factor_value": 1.2},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "grade_slot_multiplier",
        "name": "Grade slot boost",
        "description": "Boost grade concepts when a grade slot is present.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 210,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["has_grade_slot", "grade_slot_match"], "action_key": "grade_slot_multiplier", "factor_value": 1.18},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "race_slot_multiplier",
        "name": "Race slot boost",
        "description": "Boost race and ethnicity concepts when a race slot is present.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 220,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["has_race_slot", "race_slot_match"], "action_key": "race_slot_multiplier", "factor_value": 1.18},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "identifier_penalty_default",
        "name": "Identifier penalty default",
        "description": "Default identifier downranking when the prompt does not explicitly request identifiers.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 230,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["identifier_rebalance"], "exclude_context_any": ["subgroup_intent"], "action_key": "identifier_penalty_default", "penalty_value": 0.2},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "identifier_penalty_subgroup",
        "name": "Identifier penalty subgroup",
        "description": "Stronger identifier downranking when subgroup intent is present.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 240,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["identifier_rebalance", "subgroup_intent"], "action_key": "identifier_penalty_subgroup", "penalty_value": 0.35},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "identifier_limit",
        "name": "Identifier limit",
        "description": "Maximum number of identifier concepts to keep when non-identifiers are available.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 250,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "when_context_all": ["identifier_rebalance"], "action_key": "identifier_limit", "integer_value": 1},
        "_seeded": True,
    },
)


class PlannerConceptScoringPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def resolve_factor(self, *, action_key: str, context_tokens: Sequence[str], default: float) -> float:
        matches = self._matching_policies(action_key=action_key, context_tokens=context_tokens)
        if not matches:
            return default
        for row in matches:
            value = (row.get("policy_json") or {}).get("factor_value")
            if value is not None:
                return float(value)
        return default

    def resolve_penalty(self, *, action_key: str, context_tokens: Sequence[str], default: float) -> float:
        matches = self._matching_policies(action_key=action_key, context_tokens=context_tokens)
        if not matches:
            return default
        for row in matches:
            value = (row.get("policy_json") or {}).get("penalty_value")
            if value is not None:
                return float(value)
        return default

    def resolve_integer(self, *, action_key: str, context_tokens: Sequence[str], default: int) -> int:
        matches = self._matching_policies(action_key=action_key, context_tokens=context_tokens)
        if not matches:
            return default
        for row in matches:
            value = (row.get("policy_json") or {}).get("integer_value")
            if value is not None:
                return int(value)
        return default

    def _matching_policies(self, *, action_key: str, context_tokens: Sequence[str]) -> List[Dict[str, Any]]:
        context = {str(item or "").strip().lower() for item in context_tokens if str(item or "").strip()}
        out: List[Dict[str, Any]] = []
        for row in self.get_applicable_policies():
            rule = _parse_policy_rule(row.get("policy_json"))
            if rule.action_key != str(action_key or "").strip().lower():
                continue
            if rule.when_context_all and not set(rule.when_context_all).issubset(context):
                continue
            if rule.when_context_any and context.isdisjoint(set(rule.when_context_any)):
                continue
            if rule.exclude_context_any and not context.isdisjoint(set(rule.exclude_context_any)):
                continue
            out.append(row)
            if bool(row.get("stop_on_match")):
                break
        return out

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
                FROM planner_concept_scoring_policy
                WHERE is_active = 1
                ORDER BY priority ASC, id ASC
                """,
                {},
            )
        except POLICY_LOOKUP_FALLBACK_ERRORS:
            logger.exception("Failed to load planner concept scoring policies from db")
            return rows
        for db_row in db_rows:
            row = dict(db_row)
            row["policy_json"] = _coerce_json_dict(row.get("policy_json"))
            rows.append(row)
        return sorted(rows, key=lambda item: (int(item.get("priority") or 100), int(item.get("id") or 0)))


def _parse_policy_rule(value: Any) -> PlannerConceptScoringPolicyRule:
    if isinstance(value, PlannerConceptScoringPolicyRule):
        return value
    return PlannerConceptScoringPolicyRule.model_validate(_coerce_json_dict(value))


def _coerce_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("policy_json must decode to an object")
        return dict(parsed)
    raise ValueError("policy_json must be an object")


__all__ = ["PlannerConceptScoringPolicyService"]

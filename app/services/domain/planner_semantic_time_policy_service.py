from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.models.domain.planner_semantic_time_policy import PlannerSemanticTimePolicyRule
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "enrollment_time_column_preference",
        "name": "Enrollment time column preference",
        "description": "Prefer school-year columns for enrollment-oriented prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "time_column_preference",
            "when_domain_hint": "enrollment",
            "preferred_time_concept_key": "SCHOOL_YEAR",
            "preferred_column_names": ["school_year", "school_year_id", "school_year_key"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "generic_time_column_preference",
        "name": "Generic time column preference",
        "description": "Prefer school-year style time columns by default.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "action_key": "time_column_preference",
            "when_domain_hint": "generic",
            "preferred_time_concept_key": "SCHOOL_YEAR",
            "preferred_column_names": ["school_year", "year"],
        },
        "_seeded": True,
    },
)


class PlannerSemanticTimePolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def select_preferred_time_column(
        self,
        *,
        domain_hint: str,
        mapped_columns_for_time_concept: Sequence[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        rows = [dict(row) for row in mapped_columns_for_time_concept if isinstance(row, dict)]
        if not rows:
            return None
        rule = self._rule_for_domain_hint(domain_hint=domain_hint)
        concept_key = str((rule or {}).get("preferred_time_concept_key") or "SCHOOL_YEAR").upper()
        preferred_names = [str(name).lower() for name in list((rule or {}).get("preferred_column_names") or ["school_year", "year"])]
        rows.sort(
            key=lambda row: (
                0 if str(row.get("concept_key") or "").strip().upper() == concept_key else 1,
                0 if str(row.get("column_name") or "").strip().lower() in preferred_names else 1,
                -(_to_float(row.get("effective_weight")) or _to_float(row.get("final_score")) or 0.0),
                _to_int(row.get("model_column_id")) or 0,
            )
        )
        return rows[0]

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
                  scope_vertical_norm,
                  priority,
                  is_active,
                  stop_on_match,
                  policy_json
                FROM planner_semantic_time_policy
                WHERE is_active = 1
                ORDER BY priority ASC, id ASC
                """,
                {},
            )
        except Exception:
            logger.exception("Failed to load planner semantic time policies from db")
            return rows
        for db_row in db_rows:
            row = dict(db_row)
            row["policy_json"] = _coerce_json_dict(row.get("policy_json"))
            rows.append(row)
        return sorted(rows, key=lambda item: (int(item.get("priority") or 100), int(item.get("id") or 0)))

    def _rule_for_domain_hint(self, *, domain_hint: str) -> Dict[str, Any]:
        normalized = str(domain_hint or "generic").strip().lower() or "generic"
        fallback: Optional[Dict[str, Any]] = None
        for row in self.get_applicable_policies():
            rule = _parse_policy_rule(row.get("policy_json"))
            if rule.when_domain_hint == "generic":
                fallback = {"preferred_time_concept_key": rule.preferred_time_concept_key, "preferred_column_names": rule.preferred_column_names}
            if rule.when_domain_hint == normalized:
                return {"preferred_time_concept_key": rule.preferred_time_concept_key, "preferred_column_names": rule.preferred_column_names}
        return fallback or {"preferred_time_concept_key": "SCHOOL_YEAR", "preferred_column_names": ["school_year", "year"]}


def _parse_policy_rule(value: Any) -> PlannerSemanticTimePolicyRule:
    if isinstance(value, PlannerSemanticTimePolicyRule):
        return value
    return PlannerSemanticTimePolicyRule.model_validate(_coerce_json_dict(value))


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
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


__all__ = ["PlannerSemanticTimePolicyService"]

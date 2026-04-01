from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.models.domain.planner_capability_packing_policy import PlannerCapabilityPackingPolicyRule
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "school_district_context_append",
        "name": "School or district context append",
        "description": "Append a district-style name column when the prompt references a school or district context.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_any": ["school_or_district_prompt"],
            "append_first_match_column_names": ["lea_name", "district_name", "district"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_listing_location_append",
        "name": "School listing location append",
        "description": "Append city and state columns for school listing prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["school_listing"],
            "append_column_names": ["city"],
            "append_first_match_column_names": ["state_code", "state"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_listing_city_state_cleanup",
        "name": "School listing city state cleanup",
        "description": "Suppress technical state-school codes when a city/state school listing prompt has a preferred state column.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["school_listing", "city_state_prompt"],
            "required_capability_features": ["HAS_PREFERRED_STATE_COLUMN"],
            "excluded_column_names": ["state_school_code"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "nativity_filter_support",
        "name": "Nativity filter support",
        "description": "Ensure nativity prompts expose birth-country style filter columns.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 130,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["nativity_prompt"],
            "required_filter_column_names": ["birth_country", "country_of_birth", "date_entered_us"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "canonical_name_preference",
        "name": "Canonical name preference",
        "description": "Prefer canonical first/last name columns over preferred-name variants when the prompt implies identity lookup and does not explicitly ask for preferred names.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 140,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["canonical_name_preference_prompt"],
            "exclude_signals_any": ["explicit_preferred_name_request"],
            "required_capability_features": ["HAS_CANONICAL_NAME_COLUMNS"],
            "prefer_canonical_name_columns": True,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "name_constraint_support",
        "name": "Name constraint support",
        "description": "Ensure prompts with explicit first/last-name constraints surface the needed name columns.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "scope_vertical_norm": None,
        "priority": 150,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["name_constraint_prompt"],
            "include_name_constraint_columns": True,
        },
        "_seeded": True,
    },
)


class PlannerCapabilityPackingPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def get_packing_requirements(
        self,
        *,
        workspace_id: Optional[str],
        vertical_norm: Optional[str],
        prompt_signals: Sequence[str],
        capability_features: Sequence[str],
    ) -> Dict[str, Any]:
        signals = [str(item or "").strip() for item in prompt_signals if str(item or "").strip()]
        features = {str(item or "").strip().upper() for item in capability_features if str(item or "").strip()}
        if not signals:
            return {
                "prepend_column_names": [],
                "append_column_names": [],
                "append_first_match_column_names": [],
                "append_first_match_column_name_groups": [],
                "excluded_column_names": [],
                "required_filter_column_names": [],
                "prefer_canonical_name_columns": False,
                "include_name_constraint_columns": False,
                "matched_policies": [],
            }

        prepend_column_names: List[str] = []
        append_column_names: List[str] = []
        append_first_match_column_names: List[str] = []
        append_first_match_column_name_groups: List[List[str]] = []
        excluded_column_names: List[str] = []
        required_filter_column_names: List[str] = []
        prefer_canonical_name_columns = False
        include_name_constraint_columns = False
        matched_policies: List[str] = []
        prepend_seen: set[str] = set()
        append_seen: set[str] = set()
        append_first_seen: set[str] = set()
        excluded_seen: set[str] = set()
        filter_seen: set[str] = set()

        for row in self.get_applicable_policies(workspace_id=workspace_id, vertical_norm=vertical_norm):
            rule = _parse_policy_rule(row.get("policy_json"))
            if not _rule_matches(rule=rule, prompt_signals=signals, capability_features=features):
                continue
            matched_policies.append(str(row.get("policy_key") or ""))
            for column_name in rule.prepend_column_names:
                if column_name not in prepend_seen:
                    prepend_seen.add(column_name)
                    prepend_column_names.append(column_name)
            for column_name in rule.append_column_names:
                if column_name not in append_seen:
                    append_seen.add(column_name)
                    append_column_names.append(column_name)
            for column_name in rule.append_first_match_column_names:
                if column_name not in append_first_seen:
                    append_first_seen.add(column_name)
                    append_first_match_column_names.append(column_name)
            if rule.append_first_match_column_names:
                append_first_match_column_name_groups.append(list(rule.append_first_match_column_names))
            for column_name in rule.excluded_column_names:
                if column_name not in excluded_seen:
                    excluded_seen.add(column_name)
                    excluded_column_names.append(column_name)
            for column_name in rule.required_filter_column_names:
                if column_name not in filter_seen:
                    filter_seen.add(column_name)
                    required_filter_column_names.append(column_name)
            prefer_canonical_name_columns = prefer_canonical_name_columns or bool(rule.prefer_canonical_name_columns)
            include_name_constraint_columns = include_name_constraint_columns or bool(rule.include_name_constraint_columns)
            if bool(row.get("stop_on_match")):
                break

        return {
            "prepend_column_names": prepend_column_names,
            "append_column_names": append_column_names,
            "append_first_match_column_names": append_first_match_column_names,
            "append_first_match_column_name_groups": append_first_match_column_name_groups,
            "excluded_column_names": excluded_column_names,
            "required_filter_column_names": required_filter_column_names,
            "prefer_canonical_name_columns": prefer_canonical_name_columns,
            "include_name_constraint_columns": include_name_constraint_columns,
            "matched_policies": [item for item in matched_policies if item],
        }

    def get_applicable_policies(
        self,
        *,
        workspace_id: Optional[str],
        vertical_norm: Optional[str],
    ) -> List[Dict[str, Any]]:
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
                FROM planner_capability_packing_policy
                WHERE is_active = 1
                  AND (
                    scope_type = 'global'
                    OR (scope_type = 'vertical' AND scope_vertical_norm = :vertical_norm)
                    OR (scope_type = 'workspace' AND scope_workspace_id = :workspace_id)
                  )
                ORDER BY priority ASC, id ASC
                """,
                {
                    "workspace_id": str(workspace_id or "") or None,
                    "vertical_norm": str(vertical_norm or "").strip().lower() or None,
                },
            )
        except Exception:
            logger.exception("Failed to load planner capability packing policies from db")
            return rows

        keyed_rows: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        for row in rows:
            key = (
                str(row.get("policy_key") or ""),
                str(row.get("scope_workspace_id") or ""),
                str(row.get("scope_vertical_norm") or ""),
            )
            keyed_rows[key] = row
        for db_row in db_rows:
            row = dict(db_row)
            row["policy_json"] = _coerce_json_dict(row.get("policy_json"))
            key = (
                str(row.get("policy_key") or ""),
                str(row.get("scope_workspace_id") or ""),
                str(row.get("scope_vertical_norm") or ""),
            )
            keyed_rows[key] = row
        return sorted(keyed_rows.values(), key=lambda item: (int(item.get("priority") or 100), int(item.get("id") or 0)))


def _parse_policy_rule(value: Any) -> PlannerCapabilityPackingPolicyRule:
    if isinstance(value, PlannerCapabilityPackingPolicyRule):
        return value
    return PlannerCapabilityPackingPolicyRule.model_validate(_coerce_json_dict(value))


def _coerce_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("policy_json must decode to an object")
        return dict(parsed)
    raise ValueError("policy_json must be an object")


def _rule_matches(
    *,
    rule: PlannerCapabilityPackingPolicyRule,
    prompt_signals: Sequence[str],
    capability_features: set[str],
) -> bool:
    signal_set = {str(item or "").strip() for item in prompt_signals if str(item or "").strip()}
    if rule.when_signals_all and not set(rule.when_signals_all).issubset(signal_set):
        return False
    if rule.when_signals_any and signal_set.isdisjoint(set(rule.when_signals_any)):
        return False
    if rule.exclude_signals_any and not signal_set.isdisjoint(set(rule.exclude_signals_any)):
        return False
    if rule.required_capability_features and not set(rule.required_capability_features).issubset(capability_features):
        return False
    return True


__all__ = ["PlannerCapabilityPackingPolicyService"]

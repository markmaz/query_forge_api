from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.planner_signal_policy import (
    PlannerSignalPolicyRule,
    PlannerSignalPolicyUpsertRequest,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.policy_scope_service import (
    annotate_effective_rows,
    global_workspace_query_predicate,
    require_global_workspace_scope,
    sort_and_dedupe_global_workspace_policies,
)
from app.services.planner_domain.prompt_intents import (
    _prompt_explicitly_requests_preferred_name,
    _prompt_has_adm_intent,
    _prompt_has_city_state_pattern,
    _prompt_has_name_constraint,
    _prompt_has_nativity,
    _prompt_implies_staff_work_context,
    _prompt_implies_student_school_context,
    _prompt_mentions_school_or_district,
    _prompt_prefers_canonical_name_columns,
)

_SCHOOL_LITERAL_SUFFIXES = ("elementary", "middle", "high", "academy", "campus", "school")
_SCHOOL_LITERAL_STOPWORDS = ("the", "a", "an", "all", "show", "list", "give", "display", "return", "find", "me", "has", "have")

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "student_listing_signal",
        "name": "Student listing signal",
        "description": "Detect list-style student roster prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["student_listing", "listing_intent", "needs_student_identity"],
            "match_type": "regex",
            "patterns": [r"\b(show|list|give|display|return|find)\b.*\b(student|students|kid|kids)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_aggregate_signal",
        "name": "Student aggregate signal",
        "description": "Detect aggregate student prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["student_aggregate", "aggregate_intent"],
            "match_type": "regex",
            "patterns": [
                r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(student|students|kid|kids)\b"
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_listing_signal",
        "name": "Staff listing signal",
        "description": "Detect list-style staff prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["staff_listing", "listing_intent"],
            "match_type": "regex",
            "patterns": [r"\b(show|list|give|display|return|find)\b.*\b(staff|teachers?|employees?)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_aggregate_signal",
        "name": "Staff aggregate signal",
        "description": "Detect aggregate staff prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 130,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["staff_aggregate", "aggregate_intent"],
            "match_type": "regex",
            "patterns": [
                r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(staff|teachers?|employees?)\b"
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_listing_signal",
        "name": "School listing signal",
        "description": "Detect list-style school prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 140,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["school_listing", "listing_intent"],
            "match_type": "regex",
            "patterns": [r"\b(show|list|give|display|return|find)\b.*\bschools?\b(?!\s+year)"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_aggregate_signal",
        "name": "School aggregate signal",
        "description": "Detect aggregate school prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 150,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["school_aggregate", "aggregate_intent"],
            "match_type": "regex",
            "patterns": [
                r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(school|schools)\b"
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "district_literal_signal",
        "name": "District literal signal",
        "description": "Detect district or LEA terms.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 160,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["district_literal_present"],
            "match_type": "regex",
            "patterns": [r"\b(district|school district|lea|local education agency)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "time_constraint_signal",
        "name": "Time constraint signal",
        "description": "Detect direct time phrases and month names.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 170,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["time_constraint_present"],
            "match_type": "regex",
            "patterns": [
                r"\b(this year|last year|current school year|school year|today|yesterday|last month|this month)\b",
                r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "age_extreme_signal",
        "name": "Age extreme signal",
        "description": "Detect oldest or youngest prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 180,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["age_extreme_prompt"],
            "match_type": "regex",
            "patterns": [r"\b(oldest|youngest|eldest)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "birth_month_signal",
        "name": "Birth month signal",
        "description": "Detect birthday or birth-month prompts with an explicit month.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 190,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["birth_month_prompt"],
            "match_type": "regex_all",
            "patterns": [
                r"\b(birthday|birthdays|birth month|birth months|birthdate|birthdates|birth date|birth dates|date of birth|dates of birth|born in|born during|births in)\b",
                r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "calendar_days_off_signal",
        "name": "Calendar days off signal",
        "description": "Detect school days-off prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 200,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["calendar_days_off_prompt"],
            "match_type": "regex",
            "patterns": [r"\b(days off|day off|off day|off days|no school|school closed|non instructional|non-instructional)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "enrollment_signal",
        "name": "Enrollment signal",
        "description": "Detect enrollment status prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 210,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["status_enrolled", "needs_enrollment_status"],
            "match_type": "regex",
            "patterns": [r"\b(currently enrolled|enrolled|active enrollment|is enrolled|enrollment)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "active_signal",
        "name": "Active signal",
        "description": "Detect active-status prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 220,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["status_active"],
            "match_type": "regex",
            "patterns": [r"\b(active|currently active)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "subgroup_signal",
        "name": "Subgroup signal",
        "description": "Detect subgroup or demographic prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 230,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["subgroup_prompt"],
            "match_type": "regex",
            "patterns": [r"\b(black|african american|african-american|hispanic|latino|el|ell|esl|lep|mll)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "program_signal",
        "name": "Program signal",
        "description": "Detect program or service participation prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 240,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["program_prompt", "needs_program_membership"],
            "match_type": "regex",
            "patterns": [r"\b(program|service|services|participation|membership)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_role_signal",
        "name": "Staff role signal",
        "description": "Detect staff role or title prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 250,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["staff_role_prompt"],
            "match_type": "regex",
            "patterns": [
                r"\b(principal|assistant\s+principal|teacher|counselor|counsellor|coach|librarian|superintendent|nurse|psychologist|social\s+worker|position\s+title|job\s+title|role)\b"
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_literal_signal",
        "name": "School literal signal",
        "description": "Detect school name literals ending with school suffixes.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 260,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["school_literal_present", "needs_school_filter"],
            "match_type": "school_literal",
            "suffixes": list(_SCHOOL_LITERAL_SUFFIXES),
            "stopwords": list(_SCHOOL_LITERAL_STOPWORDS),
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "explicit_school_key_signal",
        "name": "Explicit school key signal",
        "description": "Detect explicit requests for school ids or keys.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 270,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["explicit_school_key_request"],
            "match_type": "regex",
            "patterns": [r"\b(k_school|school\s+key|school\s+keys|school\s+id|school\s+ids|school\s+code|school\s+codes|nces)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "explicit_staff_classification_signal",
        "name": "Explicit staff classification signal",
        "description": "Detect explicit staff classification requests.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 280,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["explicit_staff_classification_request"],
            "match_type": "regex",
            "patterns": [r"\b(staff\s+classification|classification\s+code|class\s+code)\b"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "attendance_metric_signal",
        "name": "Attendance metric signal",
        "description": "Detect attendance metric requests.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 290,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["needs_attendance_metric"],
            "match_type": "substring_any",
            "patterns": ["attendance", "attend"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "grade_metric_signal",
        "name": "Grade metric signal",
        "description": "Detect grade or GPA metric requests.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 300,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["needs_grade_metric"],
            "match_type": "substring_any",
            "patterns": ["course grade", "gpa", "grade"],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_work_context_signal",
        "name": "Staff work context signal",
        "description": "Detect staff-work context prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 310,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["staff_work_context_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_implies_staff_work_context",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_school_context_signal",
        "name": "Student school context signal",
        "description": "Detect student-school context prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 320,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["student_school_context_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_implies_student_school_context",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "adm_intent_signal",
        "name": "ADM intent signal",
        "description": "Detect ADM-style prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 330,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["adm_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_has_adm_intent",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_or_district_signal",
        "name": "School or district signal",
        "description": "Detect school or district mentions.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 340,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["school_or_district_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_mentions_school_or_district",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "city_state_signal",
        "name": "City state signal",
        "description": "Detect city-state filters.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 350,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["city_state_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_has_city_state_pattern",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "nativity_signal",
        "name": "Nativity signal",
        "description": "Detect nativity prompts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 360,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["nativity_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_has_nativity",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "name_constraint_signal",
        "name": "Name constraint signal",
        "description": "Detect first-name or last-name constraints.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 370,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["name_constraint_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_has_name_constraint",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "canonical_name_preference_signal",
        "name": "Canonical name preference signal",
        "description": "Detect prompts that prefer canonical name columns.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 380,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["canonical_name_preference_prompt"],
            "match_type": "helper",
            "helper_name": "prompt_prefers_canonical_name_columns",
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "explicit_preferred_name_signal",
        "name": "Explicit preferred name signal",
        "description": "Detect explicit preferred-name requests.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 390,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "signal_keys": ["explicit_preferred_name_request"],
            "match_type": "helper",
            "helper_name": "prompt_explicitly_requests_preferred_name",
        },
        "_seeded": True,
    },
)

_HELPERS: Dict[str, Callable[[str], bool]] = {
    "prompt_implies_staff_work_context": _prompt_implies_staff_work_context,
    "prompt_implies_student_school_context": _prompt_implies_student_school_context,
    "prompt_has_adm_intent": _prompt_has_adm_intent,
    "prompt_mentions_school_or_district": _prompt_mentions_school_or_district,
    "prompt_has_city_state_pattern": _prompt_has_city_state_pattern,
    "prompt_has_nativity": _prompt_has_nativity,
    "prompt_has_name_constraint": _prompt_has_name_constraint,
    "prompt_prefers_canonical_name_columns": _prompt_prefers_canonical_name_columns,
    "prompt_explicitly_requests_preferred_name": _prompt_explicitly_requests_preferred_name,
}


class PlannerSignalPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def extract_policy_signals(self, *, prompt: str, workspace_id: str | None = None) -> list[str]:
        text = str(prompt or "").strip()
        if not text:
            return []
        signals: list[str] = []
        for row in self._get_applicable_policies(workspace_id=workspace_id):
            rule = _parse_policy_rule(row.get("policy_json"))
            if _rule_matches(rule=rule, prompt=text):
                for signal in rule.signal_keys:
                    if signal not in signals:
                        signals.append(signal)
        return signals

    def _get_applicable_policies(self, *, workspace_id: str | None = None) -> list[dict[str, Any]]:
        rows = [dict(item) for item in _SEED_POLICIES]
        if self._enable_db_lookup:
            db_rows = self._sql.execute_query_mappings(
                f"""
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
                FROM planner_signal_policy
                WHERE is_active = 1
                  AND {global_workspace_query_predicate()}
                ORDER BY priority ASC, policy_key ASC, id ASC
                """,
                {"workspace_id": str(workspace_id or "")},
            )
            rows.extend(dict(item) for item in db_rows)
        return sort_and_dedupe_global_workspace_policies(rows)

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
              priority,
              is_active,
              stop_on_match,
              policy_json,
              created_at,
              updated_at
            FROM planner_signal_policy
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
        req = PlannerSignalPolicyUpsertRequest.model_validate(payload)
        scope_type = require_global_workspace_scope(scope_type=req.scope_type)
        if scope_type == "workspace" and (req.scope_workspace_id or workspace_id) != workspace_id:
            raise ForgeError("workspace scope must match the active workspace", status_code=400)
        params = {
            "policy_key": req.policy_key,
            "name": req.name,
            "description": req.description,
            "scope_type": scope_type,
            "scope_workspace_id": req.scope_workspace_id or (workspace_id if scope_type == "workspace" else None),
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
                FROM planner_signal_policy
                WHERE policy_key = :policy_key
                  AND scope_type = :scope_type
                  AND (
                    (scope_workspace_id IS NULL AND :scope_workspace_id IS NULL)
                    OR scope_workspace_id = :scope_workspace_id
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
                    UPDATE planner_signal_policy
                    SET policy_key = :policy_key,
                        name = :name,
                        description = :description,
                        scope_type = :scope_type,
                        scope_workspace_id = :scope_workspace_id,
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
                    INSERT INTO planner_signal_policy (
                      policy_key,
                      name,
                      description,
                      scope_type,
                      scope_workspace_id,
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
                        FROM planner_signal_policy
                        WHERE policy_key = :policy_key
                          AND scope_type = :scope_type
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    policy_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if policy_id <= 0:
                    raise ForgeError("Unable to resolve planner signal policy id after insert.", status_code=500)

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
            "DELETE FROM planner_signal_policy WHERE id = :policy_id",
            {"policy_id": int(policy_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner signal policy not found", status_code=404)
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
              priority,
              is_active,
              stop_on_match,
              policy_json,
              created_at,
              updated_at
            FROM planner_signal_policy
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
            raise ForgeError("Planner signal policy not found", status_code=404)
        return dict(rows[0])


def _rule_matches(*, rule: PlannerSignalPolicyRule, prompt: str) -> bool:
    text = str(prompt or "")
    if rule.match_type == "regex":
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        return any(re.search(pattern, text, flags=flags) is not None for pattern in rule.patterns)
    if rule.match_type == "regex_all":
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        return all(re.search(pattern, text, flags=flags) is not None for pattern in rule.patterns)
    if rule.match_type == "substring_any":
        source = text if rule.case_sensitive else text.lower()
        patterns = rule.patterns if rule.case_sensitive else [pattern.lower() for pattern in rule.patterns]
        return any(pattern in source for pattern in patterns)
    if rule.match_type == "helper":
        helper = _HELPERS.get(str(rule.helper_name or "").strip())
        return bool(helper and helper(text))
    if rule.match_type == "school_literal":
        return _has_school_literal(text=text, suffixes=rule.suffixes, stopwords=rule.stopwords)
    return False


def _parse_policy_rule(value: Any) -> PlannerSignalPolicyRule:
    if isinstance(value, PlannerSignalPolicyRule):
        return value
    if isinstance(value, str):
        return PlannerSignalPolicyRule.model_validate_json(value)
    return PlannerSignalPolicyRule.model_validate(value or {})


def _has_school_literal(*, text: str, suffixes: Iterable[str], stopwords: Iterable[str]) -> bool:
    tokens = [token for token in re.findall(r"[A-Za-z0-9'&.-]+", str(text or "").lower()) if token]
    suffix_set = {str(item).strip().lower() for item in suffixes if str(item).strip()}
    stopword_set = {str(item).strip().lower() for item in stopwords if str(item).strip()}
    for idx, token in enumerate(tokens):
        if token not in suffix_set or idx == 0:
            continue
        start = max(0, idx - 4)
        preceding = [item for item in tokens[start:idx] if item not in stopword_set]
        if preceding:
            return True
    return False


def _json_safe_mapping(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.planner_prompt_intent_policy import (
    PlannerPromptIntentPolicyRule,
    PlannerPromptIntentPolicyUpsertRequest,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.policy_scope_service import (
    GLOBAL_WORKSPACE_SCOPE_TYPES,
    annotate_effective_scoped_rows,
    require_supported_scope,
    scoped_query_predicate,
    sort_and_dedupe_scoped_policies,
)

_US_STATE_ABBR = (
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
)

_SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "id": 0,
        "policy_key": "list_students_intent",
        "name": "List students intent",
        "description": "Detect list-style student prompts.",
        "scope_type": "global",
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "list_students", "regex_patterns": [r"\b(show|list|give|display|return|find)\b.*\b(student|students)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "aggregate_students_intent",
        "name": "Aggregate students intent",
        "description": "Detect aggregate student prompts.",
        "scope_type": "global",
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "aggregate_students", "regex_patterns": [r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(student|students)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "list_schools_intent",
        "name": "List schools intent",
        "description": "Detect list-style school prompts.",
        "scope_type": "global",
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "list_schools", "regex_patterns": [r"\b(show|list|give|display|return|find)\b.*\b(school|schools)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "aggregate_schools_intent",
        "name": "Aggregate schools intent",
        "description": "Detect aggregate school prompts.",
        "scope_type": "global",
        "priority": 130,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "aggregate_schools", "regex_patterns": [r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(school|schools)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "mention_students",
        "name": "Mention students",
        "description": "Detect student entity mentions.",
        "scope_type": "global",
        "priority": 140,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "mention_students", "regex_patterns": [r"\b(student|students|kid|kids)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "mention_schools",
        "name": "Mention schools",
        "description": "Detect school entity mentions.",
        "scope_type": "global",
        "priority": 150,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "mention_schools", "regex_patterns": [r"\b(school|schools)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "district_terms",
        "name": "District terms",
        "description": "Detect district or LEA phrases.",
        "scope_type": "global",
        "priority": 160,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "district_terms", "regex_patterns": [r"\b(district|school district|lea|local education agency)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "subgroup_terms",
        "name": "Subgroup terms",
        "description": "Detect subgroup terms.",
        "scope_type": "global",
        "priority": 170,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "subgroup_terms", "regex_patterns": [r"\b(black|african american|african-american|hispanic|latino|el|ell|esl|lep|mll)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "nativity_terms",
        "name": "Nativity terms",
        "description": "Detect nativity phrases.",
        "scope_type": "global",
        "priority": 180,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "nativity_terms", "substring_patterns": ["born", "birth", "birth country", "not born", "entered the us", "date entered us"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "calendar_days_off_terms",
        "name": "Calendar days off terms",
        "description": "Detect days-off phrases.",
        "scope_type": "global",
        "priority": 190,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "calendar_days_off_terms", "substring_patterns": [" days off ", " day off ", " off day ", " off days ", " no school ", " school closed ", " non instructional ", " non-instructional "]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "age_extreme_terms",
        "name": "Age extreme terms",
        "description": "Detect oldest or youngest phrases.",
        "scope_type": "global",
        "priority": 200,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "age_extreme_terms", "substring_patterns": [" oldest ", " youngest ", " eldest "]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "birth_month_terms",
        "name": "Birth month terms",
        "description": "Detect birth-month context phrases.",
        "scope_type": "global",
        "priority": 210,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "birth_month_terms", "substring_patterns": [" birthday ", " birthdays ", " birth month ", " birthdate ", " date of birth ", " born in ", " births in "]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "name_constraint_terms",
        "name": "Name constraint terms",
        "description": "Detect name-constraint phrases.",
        "scope_type": "global",
        "priority": 220,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "name_constraint_terms", "substring_patterns": ["first name", "last name", "named ", "name of "]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "explicit_preferred_name_terms",
        "name": "Explicit preferred name terms",
        "description": "Detect explicit preferred-name requests.",
        "scope_type": "global",
        "priority": 230,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "explicit_preferred_name_terms", "substring_patterns": [" preferred name ", " preferred first name ", " preferred last name ", " preferred names "]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "staff_work_hint",
        "name": "Staff work hint",
        "description": "Detect staff work context phrases.",
        "scope_type": "global",
        "priority": 240,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "staff_work_hint", "regex_patterns": [r"\b(work(s|ed|ing)?|workplace|employed|employment|teach(es|ing)?|teacher|staff|job|principal|assistant\s+principal|counselor|counsellor)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_attend_hint",
        "name": "Student attend hint",
        "description": "Detect student-school context phrases.",
        "scope_type": "global",
        "priority": 250,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "student_attend_hint", "regex_patterns": [r"\b(goes to|attend(s|ed|ing)?|enroll(ed|ment|ing)?|student)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "adm_hint",
        "name": "ADM hint",
        "description": "Detect ADM phrases.",
        "scope_type": "global",
        "priority": 260,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "adm_hint", "regex_patterns": [r"\b(adm|average\s+daily\s+membership|base\s+adm|daily\s+membership|normalized\s+adm)\b"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "city_state_abbr",
        "name": "City state abbreviation",
        "description": "Detect city-state abbreviation patterns.",
        "scope_type": "global",
        "priority": 270,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "city_state_abbr", "regex_patterns": [r",\s*([a-z]{2})\b"], "state_codes": list(_US_STATE_ABBR)},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "month_names",
        "name": "Month names",
        "description": "Known month names for prompt analysis.",
        "scope_type": "global",
        "priority": 280,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "month_names", "substring_patterns": ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]},
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "time_phrases",
        "name": "Time phrases",
        "description": "Known time phrases for prompt analysis.",
        "scope_type": "global",
        "priority": 290,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {"version": 1, "action_key": "time_phrases", "substring_patterns": ["this year", "last year", "current school year", "school year"]},
        "_seeded": True,
    },
)


class PlannerPromptIntentPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def looks_like_list_students(
        self,
        prompt: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> bool:
        text = str(prompt or "").strip()
        if text == "":
            return False
        if self.matches_regex("aggregate_students", text, workspace_id=workspace_id, vertical_norm=vertical_norm):
            return False
        if self.matches_regex("list_students", text, workspace_id=workspace_id, vertical_norm=vertical_norm):
            return True
        return self.matches_regex("mention_students", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def looks_like_list_schools(
        self,
        prompt: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> bool:
        text = str(prompt or "").strip()
        if text == "":
            return False
        if self.matches_regex("aggregate_schools", text, workspace_id=workspace_id, vertical_norm=vertical_norm):
            return False
        if self.matches_regex("list_schools", text, workspace_id=workspace_id, vertical_norm=vertical_norm):
            return True
        return self.matches_regex("mention_schools", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_mentions_students(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        return self.matches_regex("mention_students", str(prompt or ""), workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_mentions_school_or_district(
        self,
        prompt: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> bool:
        text = str(prompt or "")
        return self.matches_regex("mention_schools", text, workspace_id=workspace_id, vertical_norm=vertical_norm) or self.matches_regex(
            "district_terms", text, workspace_id=workspace_id, vertical_norm=vertical_norm
        )

    def prompt_has_subgroup(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        return self.matches_regex("subgroup_terms", str(prompt or ""), workspace_id=workspace_id, vertical_norm=vertical_norm)

    def extract_subgroup_terms(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> list[str]:
        return _dedupe_text_items(
            self.extract_regex_terms("subgroup_terms", str(prompt or ""), workspace_id=workspace_id, vertical_norm=vertical_norm)
        )

    def prompt_has_nativity(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        return self.matches_substring("nativity_terms", str(prompt or "").lower(), workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_has_calendar_days_off(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        text = f" {str(prompt or '').strip().lower()} "
        if text.strip() == "":
            return False
        return self.matches_substring("calendar_days_off_terms", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_has_age_extreme(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        text = f" {str(prompt or '').strip().lower()} "
        if text.strip() == "":
            return False
        return self.matches_substring("age_extreme_terms", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_has_birth_month_constraint(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        text = f" {str(prompt or '').strip().lower()} "
        if text.strip() == "":
            return False
        if not self.matches_substring("birth_month_terms", text, workspace_id=workspace_id, vertical_norm=vertical_norm):
            return False
        return self.extract_named_month_number(text, workspace_id=workspace_id, vertical_norm=vertical_norm) is not None

    def prompt_has_name_constraint(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        return self.matches_substring("name_constraint_terms", str(prompt or "").lower(), workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_explicitly_requests_preferred_name(
        self,
        prompt: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> bool:
        text = f" {str(prompt or '').strip().lower()} "
        if text.strip() == "":
            return False
        return self.matches_substring("explicit_preferred_name_terms", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_has_adm_intent(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        text = str(prompt or "").strip().lower()
        if text == "":
            return False
        return self.matches_regex("adm_hint", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_implies_staff_work_context(
        self,
        prompt: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> bool:
        text = str(prompt or "").strip().lower()
        if text == "":
            return False
        if self.matches_regex("student_attend_hint", text, workspace_id=workspace_id, vertical_norm=vertical_norm) and not self.matches_regex(
            "staff_work_hint", text, workspace_id=workspace_id, vertical_norm=vertical_norm
        ):
            return False
        return self.matches_regex("staff_work_hint", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_implies_student_school_context(
        self,
        prompt: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> bool:
        text = str(prompt or "").strip().lower()
        if text == "":
            return False
        if self.matches_regex("staff_work_hint", text, workspace_id=workspace_id, vertical_norm=vertical_norm) and not self.matches_regex(
            "student_attend_hint", text, workspace_id=workspace_id, vertical_norm=vertical_norm
        ):
            return False
        return self.matches_regex("student_attend_hint", text, workspace_id=workspace_id, vertical_norm=vertical_norm)

    def prompt_has_city_state_pattern(
        self,
        prompt: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> bool:
        text = str(prompt or "").strip().lower()
        if text == "":
            return False
        match = self.first_regex_match("city_state_abbr", text, workspace_id=workspace_id, vertical_norm=vertical_norm)
        if match is None:
            return False
        token = str(match.group(1) or "").strip().lower()
        return token in set(self.substring_patterns("city_state_abbr", state_codes=True, workspace_id=workspace_id, vertical_norm=vertical_norm))

    def extract_time_phrases(self, prompt: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> list[str]:
        text = str(prompt or "").lower()
        phrases: list[str] = []
        configured = self.substring_patterns("time_phrases", workspace_id=workspace_id, vertical_norm=vertical_norm)
        for phrase in configured[:3]:
            if phrase in text:
                phrases.append(phrase)
        if "school year" in text and not phrases and "school year" in configured:
            phrases.append("school year")
        return _dedupe_text_items(phrases)

    def extract_named_month_number(
        self,
        text: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> Optional[int]:
        prompt_text = str(text or "").strip().lower()
        if prompt_text == "":
            return None
        month_names = self.substring_patterns("month_names", workspace_id=workspace_id, vertical_norm=vertical_norm)
        month_map = {name: idx + 1 for idx, name in enumerate(month_names)}
        for name in month_names:
            if re.search(rf"\b{re.escape(name)}\b", prompt_text) is not None:
                return month_map.get(name)
        return None

    def matches_regex(self, action_key: str, text: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        rule = self._get_rule_index(workspace_id=workspace_id, vertical_norm=vertical_norm).get(action_key)
        if rule is None:
            return False
        return any(re.search(pattern, text, flags=re.IGNORECASE) is not None for pattern in rule.regex_patterns)

    def first_regex_match(
        self,
        action_key: str,
        text: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> re.Match[str] | None:
        rule = self._get_rule_index(workspace_id=workspace_id, vertical_norm=vertical_norm).get(action_key)
        if rule is None:
            return None
        for pattern in rule.regex_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is not None:
                return match
        return None

    def extract_regex_terms(
        self,
        action_key: str,
        text: str,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> list[str]:
        rule = self._get_rule_index(workspace_id=workspace_id, vertical_norm=vertical_norm).get(action_key)
        if rule is None:
            return []
        out: list[str] = []
        for pattern in rule.regex_patterns:
            out.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
        return out

    def matches_substring(self, action_key: str, text: str, *, workspace_id: str | None = None, vertical_norm: str | None = None) -> bool:
        return any(token in text for token in self.substring_patterns(action_key, workspace_id=workspace_id, vertical_norm=vertical_norm))

    def substring_patterns(
        self,
        action_key: str,
        *,
        state_codes: bool = False,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> list[str]:
        rule = self._get_rule_index(workspace_id=workspace_id, vertical_norm=vertical_norm).get(action_key)
        if rule is None:
            return []
        return list(rule.state_codes if state_codes else rule.substring_patterns)

    def _get_rule_index(
        self,
        *,
        workspace_id: str | None = None,
        vertical_norm: str | None = None,
    ) -> dict[str, PlannerPromptIntentPolicyRule]:
        del vertical_norm
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
                    FROM planner_prompt_intent_policy
                    WHERE is_active = 1
                    AND {scoped_query_predicate()}
                ORDER BY priority ASC, policy_key ASC, id ASC
                """,
                {
                    "workspace_id": str(workspace_id or ""),
                },
            )
            rows.extend(dict(item) for item in db_rows)
        return _build_rule_index(sort_and_dedupe_scoped_policies(rows))

    def list_policies(
        self,
        *,
        workspace_id: str,
        vertical_norm: str = "generic",
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
            FROM planner_prompt_intent_policy
            WHERE {scoped_query_predicate()}
            {"AND is_active = 1" if not include_inactive else ""}
            """,
            {
                "workspace_id": str(workspace_id),
            },
        )
        rows.extend({**dict(row), "_seeded": False} for row in db_rows)

        policies: list[dict[str, Any]] = []
        for row in rows:
            payload = _json_safe_mapping(dict(row))
            payload.pop("scope_vertical_norm", None)
            payload["policy_json"] = _parse_policy_rule(payload.get("policy_json")).model_dump()
            payload["is_seeded"] = bool(payload.get("_seeded"))
            payload["can_edit"] = not payload["is_seeded"]
            payload["can_delete"] = not payload["is_seeded"]
            policies.append(payload)

        return {
            "workspace_id": str(workspace_id),
            "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
            "can_edit": True,
            "policies": annotate_effective_scoped_rows(policies),
        }

    def upsert_policy(
        self,
        *,
        workspace_id: str,
        payload: Any,
    ) -> Dict[str, Any]:
        req = PlannerPromptIntentPolicyUpsertRequest.model_validate(payload)
        scope_type = require_supported_scope(
            scope_type=req.scope_type,
            allowed_scope_types=GLOBAL_WORKSPACE_SCOPE_TYPES,
            family_label="planner prompt intent policies",
        )
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
                FROM planner_prompt_intent_policy
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
                    UPDATE planner_prompt_intent_policy
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
                    INSERT INTO planner_prompt_intent_policy (
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
                        FROM planner_prompt_intent_policy
                        WHERE policy_key = :policy_key
                          AND scope_type = :scope_type
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    policy_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if policy_id <= 0:
                    raise ForgeError("Unable to resolve planner prompt intent policy id after insert.", status_code=500)

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
        deleted = self._sql.execute_write(
            "DELETE FROM planner_prompt_intent_policy WHERE id = :policy_id",
            {"policy_id": int(policy_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner prompt intent policy not found", status_code=404)
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
            FROM planner_prompt_intent_policy
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
            raise ForgeError("Planner prompt intent policy not found", status_code=404)
        return dict(rows[0])


def _build_rule_index(rows: Iterable[dict[str, Any]]) -> dict[str, PlannerPromptIntentPolicyRule]:
    out: dict[str, PlannerPromptIntentPolicyRule] = {}
    for row in rows:
        rule = _parse_policy_rule(row.get("policy_json"))
        if rule.action_key in out:
            continue
        out[rule.action_key] = rule
    return out

def _dedupe_text_items(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = " ".join(str(value).strip().split())
        if token == "":
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _parse_policy_rule(value: Any) -> PlannerPromptIntentPolicyRule:
    if isinstance(value, PlannerPromptIntentPolicyRule):
        return value
    if isinstance(value, str):
        return PlannerPromptIntentPolicyRule.model_validate_json(value)
    return PlannerPromptIntentPolicyRule.model_validate(value or {})


def _json_safe_mapping(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value

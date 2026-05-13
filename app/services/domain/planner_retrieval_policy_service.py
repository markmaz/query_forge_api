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
from app.models.domain.planner_retrieval_policy import (
    PlannerRetrievalPolicyRule,
    PlannerRetrievalPolicyUpsertRequest,
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
        "policy_key": "staff_context_domain_retrieval",
        "name": "Staff context domain retrieval",
        "description": "Expand staff prompts toward assignment and workforce domains and away from unrelated student or discipline domains.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 100,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_any": ["staff_listing", "staff_aggregate", "staff_work_context_prompt"],
            "query_specs": [
                {"query": "staff assignments", "source": "vector"},
                {"query": "staff workplace", "source": "vector"},
                {"query": "teacher employment", "source": "vector"},
                {"query": "employee roster", "source": "vector"},
            ],
            "domain_name_prefer_tokens": ["staff", "assignment", "employee", "teacher", "workforce"],
            "domain_name_avoid_tokens": ["student", "discipline"],
            "domain_name_positive_bias": 0.18,
            "domain_name_negative_bias": 0.24,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "student_context_domain_retrieval",
        "name": "Student context domain retrieval",
        "description": "Expand student prompts toward enrollment and demographics domains and away from unrelated discipline domains.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 110,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_any": ["student_listing", "student_aggregate", "student_school_context_prompt"],
            "query_specs": [
                {"query": "student enrollment", "source": "vector"},
                {"query": "student demographics", "source": "vector"},
                {"query": "student profile", "source": "vector"},
            ],
            "domain_name_prefer_tokens": ["student", "demographic", "profile", "enrollment", "enrolment"],
            "domain_name_avoid_tokens": ["discipline"],
            "domain_name_positive_bias": 0.14,
            "domain_name_negative_bias": 0.12,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "adm_domain_retrieval",
        "name": "ADM domain retrieval",
        "description": "Expand ADM prompts toward membership and enrollment domains and away from calendar-only domains.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 115,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["adm_prompt"],
            "query_specs": [
                {"query": "average daily membership adm base adm", "source": "vector"},
                {"query": "normalized_adm report_period school_year", "source": "vector"},
                {"query": "is_primary_school grade_level_adm", "source": "vector"},
            ],
            "domain_name_prefer_tokens": ["adm", "membership", "enrollment", "enrolment"],
            "domain_name_avoid_tokens": ["calendar", "term"],
            "domain_name_positive_bias": 0.18,
            "domain_name_negative_bias": 0.18,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "age_extreme_domain_retrieval",
        "name": "Age extreme domain retrieval",
        "description": "Bias eldest or youngest prompts toward student demographic and birth-date domains.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 120,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["age_extreme_prompt"],
            "query_specs": [
                {"query": "student demographics birth date age", "source": "vector"},
                {"query": "student profile date of birth", "source": "vector"},
            ],
            "domain_name_prefer_tokens": ["demographic", "profile", "student"],
            "domain_name_avoid_tokens": ["program", "service", "membership"],
            "domain_name_positive_bias": 0.18,
            "domain_name_negative_bias": 0.16,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "birth_month_domain_retrieval",
        "name": "Birth month domain retrieval",
        "description": "Bias birthday and birth-month prompts toward demographic and date-of-birth domains.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 130,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["birth_month_prompt"],
            "query_specs": [
                {"query": "student demographics birth date birthday month", "source": "vector"},
                {"query": "student profile date of birth month", "source": "vector"},
            ],
            "domain_name_prefer_tokens": ["demographic", "profile", "student"],
            "domain_name_avoid_tokens": ["program", "service", "membership"],
            "domain_name_positive_bias": 0.2,
            "domain_name_negative_bias": 0.18,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "calendar_days_off_domain_retrieval",
        "name": "Calendar days off domain retrieval",
        "description": "Bias days-off prompts toward calendar and scheduling domains with additional semantic calendar queries.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 140,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["calendar_days_off_prompt"],
            "query_specs": [
                {"query": "academic calendar days off", "source": "vector"},
                {"query": "school calendar no school non instructional days", "source": "vector"},
                {"query": "calendar school day holiday schedule", "source": "vector"},
                {
                    "query": "academic calendar days off no school school day",
                    "score_boost": 0.08,
                    "reasons": ["semantic_query:calendar_days_off"],
                    "source": "semantic_vector",
                },
                {
                    "query": "non instructional days school calendar holiday schedule",
                    "score_boost": 0.06,
                    "reasons": ["semantic_query:calendar_days_off"],
                    "source": "semantic_vector",
                },
            ],
            "domain_name_prefer_tokens": ["calendar", "scheduling", "schedule", "term", "semester"],
            "domain_name_positive_bias": 0.18,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "workflow_intelligence_domain_retrieval",
        "name": "Workflow Intelligence domain retrieval",
        "description": "Bias workflow, intake, matching, assignment, offer, notification, and automation outcome prompts toward generated FlowForge Workflow Intelligence domains.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 145,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["workflow_intelligence_prompt"],
            "query_specs": [
                {
                    "query": "FlowForge workflow intelligence workflow runs status outcomes lifecycle duration production automation",
                    "score_boost": 0.12,
                    "reasons": ["workflow_intelligence"],
                    "source": "vector",
                },
                {
                    "query": "FlowForge intake events matching evaluations candidates offers responses assignments notifications",
                    "score_boost": 0.1,
                    "reasons": ["workflow_intelligence"],
                    "source": "vector",
                },
                {
                    "query": "Workflow Studio generated reporting domains workflow checkpoints assignment funnel offer outcomes data movement audit",
                    "score_boost": 0.1,
                    "reasons": ["workflow_intelligence"],
                    "source": "vector",
                },
            ],
            "domain_name_prefer_tokens": [
                "flowforge",
                "workflow",
                "intake",
                "matching",
                "assignment",
                "offer",
                "notification",
            ],
            "domain_name_avoid_tokens": ["student", "enrollment", "demographic", "school"],
            "domain_name_positive_bias": 0.24,
            "domain_name_negative_bias": 0.1,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "workflow_run_count_domain_retrieval",
        "name": "Workflow run count domain retrieval",
        "description": "Bias count-style Workflow Studio run prompts toward the generated FlowForge Workflow Runs domain.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 146,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["workflow_run_count_prompt"],
            "query_specs": [
                {
                    "query": "FlowForge Workflow Runs run count Workflow Studio runs ran today completed failed active needs attention status started completed",
                    "score_boost": 0.22,
                    "reasons": ["workflow_run_count"],
                    "source": "vector",
                }
            ],
            "domain_name_prefer_tokens": ["workflow runs"],
            "domain_name_avoid_tokens": [
                "intake",
                "checkpoint",
                "matching",
                "assignment",
                "offer",
                "notification",
                "artifact",
                "audit",
            ],
            "domain_name_positive_bias": 0.36,
            "domain_name_negative_bias": 0.16,
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "subgroup_semantic_retrieval",
        "name": "Subgroup semantic retrieval",
        "description": "Expand subgroup prompts toward race, ethnicity, and language semantics.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 150,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_signals_all": ["subgroup_prompt"],
            "query_specs": [
                {
                    "query": "student subgroup demographics race ethnicity language",
                    "score_boost": 0.04,
                    "reasons": ["semantic_query:subgroup"],
                    "source": "semantic_vector",
                }
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "semester_semantic_retrieval",
        "name": "Semester semantic retrieval",
        "description": "Expand semantic retrieval when concept grounding points at semester or term concepts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 160,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_concept_key_patterns_any": ["SEMESTER", "TERM"],
            "query_specs": [
                {
                    "query": "academic calendar semester terms",
                    "score_boost": 0.05,
                    "reasons": ["semantic_query:semester"],
                    "source": "semantic_vector",
                }
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "school_year_semantic_retrieval",
        "name": "School year semantic retrieval",
        "description": "Expand semantic retrieval when concept grounding points at school-year concepts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 170,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_concept_key_patterns_any": ["SCHOOL_YEAR", "_YEAR"],
            "query_specs": [
                {
                    "query": "school year academic calendar enrollment",
                    "score_boost": 0.04,
                    "reasons": ["semantic_query:school_year"],
                    "source": "semantic_vector",
                }
            ],
        },
        "_seeded": True,
    },
    {
        "id": 0,
        "policy_key": "nativity_semantic_retrieval",
        "name": "Nativity semantic retrieval",
        "description": "Expand semantic retrieval when grounding points at country-of-birth style concepts.",
        "scope_type": "global",
        "scope_workspace_id": None,
        "priority": 180,
        "is_active": 1,
        "stop_on_match": 0,
        "policy_json": {
            "version": 1,
            "when_concept_key_patterns_any": ["COUNTRY"],
            "query_specs": [
                {
                    "query": "student demographics birth country nativity",
                    "score_boost": 0.06,
                    "reasons": ["semantic_query:nativity"],
                    "source": "semantic_vector",
                },
                {
                    "query": "country of birth student profile demographics",
                    "score_boost": 0.04,
                    "reasons": ["semantic_query:nativity"],
                    "source": "semantic_vector",
                }
            ],
        },
        "_seeded": True,
    },
)


class PlannerRetrievalPolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, enable_db_lookup: bool = False) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enable_db_lookup = bool(enable_db_lookup)

    def build_query_specs(
        self,
        *,
        workspace_id: Optional[str],
        prompt_signals: Sequence[str],
        semantic_concept_keys: Sequence[str],
    ) -> List[Dict[str, Any]]:
        policies = self.get_applicable_policies(workspace_id=workspace_id)
        signals = _normalized_tokens(prompt_signals, upper=False)
        concept_keys = _normalized_tokens(semantic_concept_keys, upper=True)

        merged: Dict[str, Dict[str, Any]] = {}
        for row in policies:
            rule = _parse_policy_rule(row.get("policy_json"))
            if not _rule_matches(rule=rule, prompt_signals=signals, semantic_concept_keys=concept_keys):
                continue
            for spec in rule.query_specs:
                key = spec.query.lower()
                payload = spec.model_dump()
                existing = merged.get(key)
                if existing is None:
                    merged[key] = payload
                    continue
                existing["score_boost"] = max(float(existing.get("score_boost") or 0.0), float(payload.get("score_boost") or 0.0))
                existing["reasons"] = _dedupe_text_items(list(existing.get("reasons") or []) + list(payload.get("reasons") or []))
                if str(payload.get("source") or "vector") != "vector":
                    existing["source"] = str(payload.get("source"))
            if bool(row.get("stop_on_match")):
                break
        return list(merged.values())

    def score_domain_name_bias(
        self,
        *,
        workspace_id: Optional[str],
        prompt_signals: Sequence[str],
        candidate_name: str,
    ) -> float:
        name = str(candidate_name or "").strip().lower()
        if name == "":
            return 0.0

        policies = self.get_applicable_policies(workspace_id=workspace_id)
        signals = _normalized_tokens(prompt_signals, upper=False)
        total_bias = 0.0
        for row in policies:
            rule = _parse_policy_rule(row.get("policy_json"))
            if not _rule_matches(rule=rule, prompt_signals=signals, semantic_concept_keys=()):
                continue
            if rule.domain_name_prefer_tokens and any(token in name for token in rule.domain_name_prefer_tokens):
                total_bias += float(rule.domain_name_positive_bias or 0.0)
            if rule.domain_name_avoid_tokens and any(token in name for token in rule.domain_name_avoid_tokens):
                total_bias -= float(rule.domain_name_negative_bias or 0.0)
            if bool(row.get("stop_on_match")):
                break
        return round(total_bias, 5)

    def get_applicable_policies(
        self,
        *,
        workspace_id: Optional[str],
    ) -> List[Dict[str, Any]]:
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
                      priority,
                      is_active,
                      stop_on_match,
                      policy_json
                    FROM planner_retrieval_policy
                    WHERE is_active = 1
                      AND {global_workspace_query_predicate()}
                    """,
                    {
                        "workspace_id": str(workspace_id or "").strip(),
                    },
                )
                rows.extend(dict(item) for item in db_rows)
            except POLICY_LOOKUP_FALLBACK_ERRORS as exc:  # pragma: no cover - defensive runtime fallback
                logger.warning(
                    "planner retrieval policy lookup failed workspace_id=%s err=%s",
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
        policies.sort(
            key=lambda row: (
                int(row.get("priority") or 100),
                int(row.get("id") or 0),
            )
        )
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
              priority,
              is_active,
              stop_on_match,
              policy_json,
              created_at,
              updated_at
            FROM planner_retrieval_policy
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
        req = PlannerRetrievalPolicyUpsertRequest.model_validate(payload)
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
                FROM planner_retrieval_policy
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
                    UPDATE planner_retrieval_policy
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
                    INSERT INTO planner_retrieval_policy (
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
                        FROM planner_retrieval_policy
                        WHERE policy_key = :policy_key
                          AND scope_type = :scope_type
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    policy_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if policy_id <= 0:
                    raise ForgeError("Unable to resolve planner retrieval policy id after insert.", status_code=500)

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
            "DELETE FROM planner_retrieval_policy WHERE id = :policy_id",
            {"policy_id": int(policy_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner retrieval policy not found", status_code=404)
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
            FROM planner_retrieval_policy
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
            raise ForgeError("Planner retrieval policy not found", status_code=404)
        return dict(rows[0])


def _parse_policy_rule(value: Any) -> PlannerRetrievalPolicyRule:
    if isinstance(value, PlannerRetrievalPolicyRule):
        return value
    if isinstance(value, str):
        return PlannerRetrievalPolicyRule.model_validate_json(value)
    return PlannerRetrievalPolicyRule.model_validate(value or {})


def _rule_matches(
    *,
    rule: PlannerRetrievalPolicyRule,
    prompt_signals: Sequence[str],
    semantic_concept_keys: Sequence[str],
) -> bool:
    signal_set = set(_normalized_tokens(prompt_signals, upper=False))
    concept_keys = list(_normalized_tokens(semantic_concept_keys, upper=True))

    if rule.when_signals_all and any(signal not in signal_set for signal in rule.when_signals_all):
        return False
    if rule.when_signals_any and not any(signal in signal_set for signal in rule.when_signals_any):
        return False
    if rule.exclude_signals_any and any(signal in signal_set for signal in rule.exclude_signals_any):
        return False
    if rule.when_concept_key_patterns_any:
        if not any(any(pattern in concept_key for pattern in rule.when_concept_key_patterns_any) for concept_key in concept_keys):
            return False
    return True


def _normalized_tokens(values: Sequence[str], *, upper: bool) -> List[str]:
    out: List[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        token = token.upper() if upper else token.lower()
        if token not in out:
            out.append(token)
    return out


def _dedupe_text_items(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _json_safe_mapping(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


__all__ = ["PlannerRetrievalPolicyService"]

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.planner_rerank_policy import (
    PLANNER_RERANK_CAPABILITY_KEYS,
    PlannerDomainCapabilityRecord,
    PlannerDomainCapabilityUpsertRequest,
)
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

CAPABILITY_LOOKUP_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)
CAPABILITY_RECORD_VALIDATION_ERRORS = (ValidationError, ValueError, TypeError)


class PlannerDomainCapabilityService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_capabilities(
        self,
        *,
        workspace_id: str,
        user_id: str,
        base_domain_id: int,
        vertical_norm: str = "generic",
        include_inactive: bool = False,
    ) -> Dict[str, Any]:
        domain_row = self._load_domain_row(
            workspace_id=workspace_id,
            user_id=user_id,
            domain_id=base_domain_id,
        )
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              id,
              scope_type,
              scope_workspace_id,
              scope_vertical_norm,
              base_domain_id,
              capability_key,
              support_level,
              source_type,
              source_ref,
              confidence,
              notes,
              is_active,
              created_at,
              updated_at
            FROM planner_domain_capability
            WHERE base_domain_id = :base_domain_id
              AND (
                scope_type = 'global'
                OR (scope_type = 'vertical' AND scope_vertical_norm = :vertical_norm)
                OR (scope_type = 'workspace' AND scope_workspace_id = :workspace_id)
                OR (scope_type = 'global_domain')
                OR (scope_type = 'vertical_domain' AND scope_vertical_norm = :vertical_norm)
                OR (scope_type = 'workspace_domain' AND scope_workspace_id = :workspace_id)
              )
            {"AND is_active = 1" if not include_inactive else ""}
            """,
            {
                "workspace_id": str(workspace_id),
                "vertical_norm": str(vertical_norm or "generic"),
                "base_domain_id": int(base_domain_id),
            },
        )
        capabilities: List[Dict[str, Any]] = []
        for row in rows:
            payload = _json_safe_mapping(dict(row))
            try:
                payload.update(PlannerDomainCapabilityRecord(**payload).model_dump())
            except CAPABILITY_RECORD_VALIDATION_ERRORS:
                pass
            payload["is_active"] = bool(payload.get("is_active"))
            payload["is_inherited"] = str(payload.get("scope_type") or "") not in {"workspace", "workspace_domain"}
            capabilities.append(payload)
        capabilities.sort(
            key=lambda row: (
                -_capability_rank(row)[0],
                -float(row.get("confidence") or 0.0),
                str(row.get("capability_key") or ""),
                int(row.get("id") or 0),
            )
        )
        return {
            "workspace_id": str(workspace_id),
            "vertical_norm": str(vertical_norm or "generic"),
            "base_domain_id": int(base_domain_id),
            "domain_name": str(domain_row.get("domain_name") or "").strip() or None,
            "can_edit": bool(domain_row.get("can_edit")),
            "capabilities": capabilities,
        }

    def upsert_capability(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        payload: Any,
    ) -> Dict[str, Any]:
        req = PlannerDomainCapabilityUpsertRequest.model_validate(payload)
        if req.scope_type.startswith("workspace") and (req.scope_workspace_id or workspace_id) != workspace_id:
            raise ForgeError("workspace scope must match the active workspace", status_code=400)
        domain_row = self._load_domain_row(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            domain_id=req.base_domain_id,
        )
        if not bool(domain_row.get("can_edit")):
            raise ForgeError("You do not have edit permission for this domain.", status_code=403)

        params = {
            "scope_type": req.scope_type,
            "scope_workspace_id": req.scope_workspace_id or (workspace_id if req.scope_type.startswith("workspace") else None),
            "scope_vertical_norm": req.scope_vertical_norm,
            "base_domain_id": int(req.base_domain_id),
            "capability_key": req.capability_key,
            "support_level": req.support_level,
            "source_type": req.source_type,
            "source_ref": req.source_ref,
            "confidence": float(req.confidence),
            "notes": req.notes,
            "is_active": 1 if req.is_active else 0,
        }

        existing_id: Optional[int] = None
        if req.id is not None:
            existing_row = self._load_capability_row(capability_id=int(req.id))
            if int(existing_row.get("base_domain_id") or 0) != int(req.base_domain_id):
                raise ForgeError("capability id does not belong to the requested base_domain_id", status_code=400)
            existing_id = int(existing_row["id"])
        else:
            existing = self._sql.execute_query_mappings(
                """
                SELECT id
                FROM planner_domain_capability
                WHERE base_domain_id = :base_domain_id
                  AND capability_key = :capability_key
                  AND (
                    (scope_workspace_id IS NULL AND :scope_workspace_id IS NULL)
                    OR scope_workspace_id = :scope_workspace_id
                  )
                  AND (
                    (scope_vertical_norm IS NULL AND :scope_vertical_norm IS NULL)
                    OR scope_vertical_norm = :scope_vertical_norm
                  )
                  AND (
                    (source_ref IS NULL AND :source_ref IS NULL)
                    OR source_ref = :source_ref
                  )
                LIMIT 1
                """,
                params,
            )
            if existing:
                existing_id = int(existing[0]["id"])

        with self._sql.transaction() as tx:
            if existing_id is not None:
                tx.execute_write(
                    """
                    UPDATE planner_domain_capability
                    SET scope_type = :scope_type,
                        scope_workspace_id = :scope_workspace_id,
                        scope_vertical_norm = :scope_vertical_norm,
                        base_domain_id = :base_domain_id,
                        capability_key = :capability_key,
                        support_level = :support_level,
                        source_type = :source_type,
                        source_ref = :source_ref,
                        confidence = :confidence,
                        notes = :notes,
                        is_active = :is_active,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :capability_id
                    """,
                    {**params, "capability_id": existing_id},
                )
                capability_id = existing_id
            else:
                insert_result = tx.execute_insert(
                    """
                    INSERT INTO planner_domain_capability (
                      scope_type,
                      scope_workspace_id,
                      scope_vertical_norm,
                      base_domain_id,
                      capability_key,
                      support_level,
                      source_type,
                      source_ref,
                      confidence,
                      notes,
                      is_active
                    ) VALUES (
                      :scope_type,
                      :scope_workspace_id,
                      :scope_vertical_norm,
                      :base_domain_id,
                      :capability_key,
                      :support_level,
                      :source_type,
                      :source_ref,
                      :confidence,
                      :notes,
                      :is_active
                    )
                    """,
                    params,
                )
                capability_id = int(getattr(insert_result, "lastrowid", 0) or 0)
                if capability_id <= 0:
                    rows = self._sql.execute_query_mappings(
                        """
                        SELECT id
                        FROM planner_domain_capability
                        WHERE base_domain_id = :base_domain_id
                          AND capability_key = :capability_key
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        params,
                    )
                    capability_id = int(((rows[0] if rows else {}) or {}).get("id") or 0)
                if capability_id <= 0:
                    raise ForgeError("Unable to resolve planner domain capability id after insert.", status_code=500)

        return {
            "capability_id": capability_id,
            "scope_type": params["scope_type"],
            "scope_workspace_id": params["scope_workspace_id"],
            "scope_vertical_norm": params["scope_vertical_norm"],
            "base_domain_id": params["base_domain_id"],
            "capability_key": params["capability_key"],
            "support_level": params["support_level"],
            "source_type": params["source_type"],
            "source_ref": params["source_ref"],
            "confidence": params["confidence"],
            "notes": params["notes"],
            "is_active": bool(params["is_active"]),
        }

    def delete_capability(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        capability_id: int,
    ) -> Dict[str, Any]:
        row = self._load_capability_row(capability_id=capability_id)
        domain_row = self._load_domain_row(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            domain_id=int(row.get("base_domain_id") or 0),
        )
        if not bool(domain_row.get("can_edit")):
            raise ForgeError("You do not have edit permission for this domain.", status_code=403)
        deleted = self._sql.execute_write(
            "DELETE FROM planner_domain_capability WHERE id = :capability_id",
            {"capability_id": int(capability_id)},
        )
        if deleted <= 0:
            raise ForgeError("Planner domain capability not found", status_code=404)
        return {
            "deleted": True,
            "capability_id": int(capability_id),
        }

    def resolve_capabilities(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        explicit_rows = self._load_effective_capability_rows(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            base_domain_id=base_domain_id,
        )
        inferred_rows = _infer_capability_rows(capabilities=capabilities, shortlisted_columns=shortlisted_columns)

        by_key: Dict[str, Dict[str, Any]] = {}
        for row in inferred_rows + explicit_rows:
            record = PlannerDomainCapabilityRecord(**row)
            existing = by_key.get(record.capability_key)
            record_payload = record.model_dump()
            if existing is None or _capability_rank(record_payload) >= _capability_rank(existing):
                by_key[record.capability_key] = record_payload

        present = sorted(by_key.keys())
        return {
            "present": present,
            "records": [by_key[key] for key in present],
            "explicit_records": explicit_rows,
            "inferred_records": inferred_rows,
        }

    def _load_effective_capability_rows(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
    ) -> List[Dict[str, Any]]:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  scope_type,
                  scope_workspace_id,
                  scope_vertical_norm,
                  base_domain_id,
                  capability_key,
                  support_level,
                  source_type,
                  source_ref,
                  confidence,
                  notes
                FROM planner_domain_capability
                WHERE is_active = 1
                  AND base_domain_id = :base_domain_id
                  AND (
                    scope_type = 'global'
                    OR (scope_type = 'vertical' AND scope_vertical_norm = :vertical_norm)
                    OR (scope_type = 'workspace' AND scope_workspace_id = :workspace_id)
                    OR (scope_type = 'global_domain')
                    OR (scope_type = 'vertical_domain' AND scope_vertical_norm = :vertical_norm)
                    OR (scope_type = 'workspace_domain' AND scope_workspace_id = :workspace_id)
                  )
                """,
                {
                    "workspace_id": str(workspace_id),
                    "vertical_norm": str(vertical_norm or "generic"),
                    "base_domain_id": int(base_domain_id),
                },
            )
        except CAPABILITY_LOOKUP_FALLBACK_ERRORS as exc:  # pragma: no cover - defensive runtime fallback
            logger.warning(
                "planner domain capability lookup failed workspace_id=%s vertical_norm=%s base_domain_id=%s err=%s",
                workspace_id,
                vertical_norm,
                base_domain_id,
                exc,
            )
            return []
        by_key: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            try:
                record = PlannerDomainCapabilityRecord(**dict(row))
            except CAPABILITY_RECORD_VALIDATION_ERRORS:
                continue
            current = by_key.get(record.capability_key)
            record_payload = record.model_dump()
            if current is None or _capability_rank(record_payload) >= _capability_rank(current):
                by_key[record.capability_key] = record_payload
        return [by_key[key] for key in sorted(by_key)]

    def _load_domain_row(self, *, workspace_id: str, user_id: str, domain_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              d.name AS domain_name,
              udm.can_edit
            FROM domain d
            JOIN user_domain_mapping udm
              ON udm.domain_id = d.id
             AND udm.user_id = :user_id
             AND udm.can_read = 1
            WHERE d.workspace_id = :workspace_id
              AND d.id = :domain_id
              AND d.is_active = 1
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id),
                "user_id": str(user_id),
                "domain_id": int(domain_id),
            },
        )
        if not rows:
            raise ForgeError("Domain not found or access denied", status_code=404)
        return dict(rows[0])

    def _load_capability_row(self, *, capability_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              scope_type,
              scope_workspace_id,
              scope_vertical_norm,
              base_domain_id,
              capability_key,
              support_level,
              source_type,
              source_ref,
              confidence,
              notes,
              is_active
            FROM planner_domain_capability
            WHERE id = :capability_id
            LIMIT 1
            """,
            {"capability_id": int(capability_id)},
        )
        if not rows:
            raise ForgeError("Planner domain capability not found", status_code=404)
        return dict(rows[0])


def _capability_rank(row: Mapping[str, Any]) -> Tuple[int, float]:
    scope_type = str(row.get("scope_type") or "").strip().lower()
    scope_rank = {
        "workspace_domain": 6,
        "workspace": 5,
        "vertical_domain": 4,
        "vertical": 3,
        "global_domain": 2,
        "global": 1,
    }.get(scope_type, 0)
    return scope_rank, float(row.get("confidence") or 0.0)


def _json_safe_mapping(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _all_columns(capabilities: Mapping[str, Any], shortlisted_columns: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for row in (
        list(capabilities.get("dimensions") or [])
        + list(capabilities.get("time_columns") or [])
        + list(capabilities.get("filter_columns") or [])
        + list(shortlisted_columns or [])
    ):
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("column_key") or "").strip().lower()
        if key == "" or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _infer_capability_rows(
    *,
    capabilities: Mapping[str, Any],
    shortlisted_columns: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    all_rows = _all_columns(capabilities, shortlisted_columns)
    domain_metrics = [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, Mapping)]
    present: Set[str] = set()

    for row in all_rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        semantic_type = str(row.get("semantic_type") or "").strip().lower()

        if _is_student_identity_column_name(col_name):
            present.add("STUDENT_IDENTITY")
        if _is_birth_date_column_name(col_name):
            present.add("BIRTH_DATE")
        if _is_age_column_name(col_name):
            present.add("AGE")
        if col_name in {"staff_unique_id", "local_staff_id", "staff_id", "email_address"}:
            present.add("STAFF_IDENTITY")
        if col_name in {"school_name"} or semantic_type == "attribute.school.name":
            present.add("SCHOOL_NAME")
        if _is_calendar_date_column_name(col_name):
            present.add("CALENDAR_DATE")
        if col_name in {"district_name", "lea_name"}:
            present.add("DISTRICT_NAME")
        if col_name in {"school_id", "k_school", "education_organization_id"}:
            present.add("SCHOOL_IDENTITY")
        if _is_school_day_flag_column_name(col_name):
            present.add("SCHOOL_DAY_FLAG")
        if _is_non_instructional_day_column_name(col_name):
            present.add("NON_INSTRUCTIONAL_DAY")
        if col_name in {"position_title", "classroom_position", "job_title", "role"}:
            present.add("STAFF_ROLE")
        if any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
            present.add("RACE_ETHNICITY")
        if "gender" in col_name or "sex" in col_name:
            present.add("GENDER")
        if "grade" in col_name and "grading" not in col_name:
            present.add("GRADE_LEVEL")
        if any(token in col_name for token in ("is_enrolled", "enrollment_status", "is_active_enrollment")):
            present.add("ENROLLMENT_STATUS")
        if any(token in col_name for token in ("program", "participation_status", "service")):
            present.add("PROGRAM_MEMBERSHIP")

    for row in domain_metrics:
        metric_key = str(row.get("metric_key") or "").strip().lower()
        label = str(row.get("label") or "").strip().lower()
        key_text = f"{metric_key} {label}"
        if "student_count" in key_text or "count of students" in key_text:
            present.add("STUDENT_COUNT")
        if "enrollment_count" in key_text or "count of enrolled" in key_text:
            present.add("ENROLLMENT_COUNT")
        if "attendance_rate" in key_text or "attendance rate" in key_text:
            present.add("ATTENDANCE_RATE")
        if "course_grade" in key_text or "grade" in key_text:
            present.add("COURSE_GRADE")
        if "discipline" in key_text and "incident" in key_text:
            present.add("DISCIPLINE_INCIDENT_COUNT")

    return [
        {
            "capability_key": capability_key,
            "support_level": "direct",
            "source_type": "heuristic_inference",
            "source_ref": "planner_capabilities",
            "confidence": 0.75,
            "scope_type": "runtime_inferred",
        }
        for capability_key in sorted(cap for cap in present if cap in PLANNER_RERANK_CAPABILITY_KEYS)
    ]


def _is_student_identity_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    if token in {"first_name", "last_name", "display_name", "safe_display_name"}:
        return True
    if token.startswith("k_student"):
        return True
    if "student_id" in token:
        return True
    return False


def _is_calendar_date_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"calendar_date", "school_calendar_date"} or (
        "calendar" in token and "date" in token
    )


def _is_birth_date_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"birth_date", "date_of_birth", "dob"} or ("birth" in token and "date" in token)


def _is_age_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token == "age" or token.endswith("_age") or token.startswith("age_")


def _is_school_day_flag_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"is_school_day", "school_day_flag", "instructional_day_flag"} or (
        "school_day" in token or "instructional_day" in token
    )


def _is_non_instructional_day_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return "non_instructional" in token or "noninstructional" in token or "day_off" in token or "days_off" in token


__all__ = ["PlannerDomainCapabilityService"]

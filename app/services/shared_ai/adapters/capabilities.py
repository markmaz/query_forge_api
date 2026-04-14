from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Protocol, Sequence

from app.services.domain.planner_domain_capability_service import PlannerDomainCapabilityService
from app.services.shared_ai.artifacts import Candidate, CapabilityMapArtifact
from app.services.shared_ai.context import PipelineContext


class CandidateCapabilityAdapter(Protocol):
    def resolve(
        self,
        *,
        context: PipelineContext,
        candidates: Sequence[Candidate],
    ) -> tuple[list[Candidate], CapabilityMapArtifact]:
        ...


class HeuristicColumnCapabilityAdapter:
    def resolve(
        self,
        *,
        context: PipelineContext,
        candidates: Sequence[Candidate],
    ) -> tuple[list[Candidate], CapabilityMapArtifact]:
        del context
        enriched: list[Candidate] = []
        capability_map: dict[str, list[str]] = {}
        records_map: dict[str, list[dict[str, Any]]] = {}

        for candidate in candidates:
            present = sorted(_infer_column_candidate_capabilities(candidate))
            capability_map[candidate.candidate_id] = present
            records_map[candidate.candidate_id] = [
                {
                    "capability_key": capability_key,
                    "support_level": "direct",
                    "source_type": "heuristic_inference",
                    "source_ref": "shared_ai:column_candidate",
                    "confidence": 0.7,
                }
                for capability_key in present
            ]
            enriched.append(replace(candidate, capabilities=present))

        artifact = CapabilityMapArtifact(
            candidate_capabilities=capability_map,
            capability_records=records_map,
            debug={"mode": "heuristic_column_capabilities"},
        )
        return enriched, artifact


class DomainCapabilityResolverAdapter:
    def __init__(self, *, resolver: PlannerDomainCapabilityService | None = None) -> None:
        self._resolver = resolver or PlannerDomainCapabilityService()

    def resolve(
        self,
        *,
        context: PipelineContext,
        candidates: Sequence[Candidate],
    ) -> tuple[list[Candidate], CapabilityMapArtifact]:
        workspace_id = str(context.workspace_id or "").strip()
        enriched: list[Candidate] = []
        capability_map: dict[str, list[str]] = {}
        records_map: dict[str, list[dict[str, Any]]] = {}

        for candidate in candidates:
            attrs = dict(candidate.attributes)
            base_domain_id = int(attrs.get("domain_id") or attrs.get("base_domain_id") or 0)
            capabilities = attrs.get("capabilities_payload") or {}
            shortlisted_columns = attrs.get("shortlisted_columns") or []
            if workspace_id and base_domain_id > 0 and isinstance(capabilities, Mapping):
                view = self._resolver.resolve_capabilities(
                    workspace_id=workspace_id,
                    base_domain_id=base_domain_id,
                    capabilities=capabilities,
                    shortlisted_columns=shortlisted_columns if isinstance(shortlisted_columns, Sequence) else [],
                )
                present = list(view.get("present") or [])
                records = list(view.get("records") or [])
            else:
                present = []
                records = []
            capability_map[candidate.candidate_id] = present
            records_map[candidate.candidate_id] = [dict(row) for row in records if isinstance(row, Mapping)]
            enriched.append(replace(candidate, capabilities=present))

        artifact = CapabilityMapArtifact(
            candidate_capabilities=capability_map,
            capability_records=records_map,
            debug={"mode": "planner_domain_capabilities"},
        )
        return enriched, artifact

def _infer_column_candidate_capabilities(candidate: Candidate) -> set[str]:
    attrs = candidate.attributes
    column_name = str(attrs.get("column_name") or candidate.label or "").strip().lower()
    semantic_type = str(attrs.get("semantic_type") or "").strip().lower()
    present: set[str] = set()

    if _is_student_identity_column_name(column_name):
        present.add("STUDENT_IDENTITY")
    if _is_birth_date_column_name(column_name):
        present.add("BIRTH_DATE")
    if _is_age_column_name(column_name):
        present.add("AGE")
    if column_name in {"staff_unique_id", "local_staff_id", "staff_id", "email_address"}:
        present.add("STAFF_IDENTITY")
    if column_name == "school_name" or semantic_type == "attribute.school.name":
        present.add("SCHOOL_NAME")
    if _is_calendar_date_column_name(column_name):
        present.add("CALENDAR_DATE")
    if column_name in {"district_name", "lea_name"}:
        present.add("DISTRICT_NAME")
    if column_name in {"school_id", "k_school", "education_organization_id"}:
        present.add("SCHOOL_IDENTITY")
    if _is_school_day_flag_column_name(column_name):
        present.add("SCHOOL_DAY_FLAG")
    if _is_non_instructional_day_column_name(column_name):
        present.add("NON_INSTRUCTIONAL_DAY")
    if column_name in {"position_title", "classroom_position", "job_title", "role"}:
        present.add("STAFF_ROLE")
    if any(token in column_name for token in ("race", "ethnicity", "hispanic", "latino")):
        present.add("RACE_ETHNICITY")
    if "gender" in column_name or "sex" in column_name:
        present.add("GENDER")
    if "grade" in column_name and "grading" not in column_name:
        present.add("GRADE_LEVEL")
    if any(token in column_name for token in ("is_enrolled", "enrollment_status", "is_active_enrollment")):
        present.add("ENROLLMENT_STATUS")
    if any(token in column_name for token in ("program", "participation_status", "service")):
        present.add("PROGRAM_MEMBERSHIP")
    return present


def _is_student_identity_column_name(col_name: str) -> bool:
    if not col_name:
        return False
    if col_name in {"first_name", "last_name", "display_name", "safe_display_name"}:
        return True
    if col_name.startswith("k_student"):
        return True
    return "student_id" in col_name


def _is_calendar_date_column_name(col_name: str) -> bool:
    if not col_name:
        return False
    return col_name in {"calendar_date", "school_calendar_date"} or ("calendar" in col_name and "date" in col_name)


def _is_birth_date_column_name(col_name: str) -> bool:
    if not col_name:
        return False
    return col_name in {"birth_date", "date_of_birth", "dob"} or ("birth" in col_name and "date" in col_name)


def _is_age_column_name(col_name: str) -> bool:
    if not col_name:
        return False
    return col_name == "age" or col_name.endswith("_age") or col_name.startswith("age_")


def _is_school_day_flag_column_name(col_name: str) -> bool:
    if not col_name:
        return False
    return col_name in {"is_school_day", "school_day_flag", "instructional_day_flag"} or (
        "school_day" in col_name or "instructional_day" in col_name
    )


def _is_non_instructional_day_column_name(col_name: str) -> bool:
    if not col_name:
        return False
    return "non_instructional" in col_name or "noninstructional" in col_name or "day_off" in col_name or "days_off" in col_name

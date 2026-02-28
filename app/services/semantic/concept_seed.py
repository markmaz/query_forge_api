from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor
from app.services.semantic.semantic_llm_schema import normalize_concept_key


class ConceptSeedService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def ensure_seeded(self, vertical_norm: str) -> Dict[str, Any]:
        vertical = _normalize_vertical(vertical_norm)
        concepts = _seed_concepts(vertical)
        aliases = _seed_aliases(vertical)

        concept_written = 0
        alias_written = 0

        for concept in concepts:
            self._sql.execute_write(
                """
                INSERT INTO semantic_concept (
                  vertical_norm,
                  concept_key,
                  name,
                  description,
                  semantic_type,
                  sub_type,
                  entity,
                  granularity_rank,
                  filter_allowed,
                  group_by_allowed,
                  aggregation_allowed,
                  is_identifier,
                  is_metric,
                  display_priority,
                  `sensitive`,
                  `status`
                ) VALUES (
                  :vertical_norm,
                  :concept_key,
                  :name,
                  :description,
                  :semantic_type,
                  :sub_type,
                  :entity,
                  :granularity_rank,
                  :filter_allowed,
                  :group_by_allowed,
                  :aggregation_allowed,
                  :is_identifier,
                  :is_metric,
                  :display_priority,
                  :sensitive,
                  :status
                )
                ON DUPLICATE KEY UPDATE
                  name = VALUES(name),
                  description = VALUES(description),
                  semantic_type = VALUES(semantic_type),
                  sub_type = VALUES(sub_type),
                  entity = VALUES(entity),
                  granularity_rank = VALUES(granularity_rank),
                  filter_allowed = VALUES(filter_allowed),
                  group_by_allowed = VALUES(group_by_allowed),
                  aggregation_allowed = VALUES(aggregation_allowed),
                  is_identifier = VALUES(is_identifier),
                  is_metric = VALUES(is_metric),
                  display_priority = VALUES(display_priority),
                  `sensitive` = VALUES(`sensitive`),
                  `status` = VALUES(`status`)
                """,
                concept,
            )
            concept_written += 1

        for alias in aliases:
            self._sql.execute_write(
                """
                INSERT INTO semantic_concept_alias (
                  vertical_norm,
                  alias_key,
                  concept_key,
                  match_kind,
                  weight
                ) VALUES (
                  :vertical_norm,
                  :alias_key,
                  :concept_key,
                  :match_kind,
                  :weight
                )
                ON DUPLICATE KEY UPDATE
                  concept_key = VALUES(concept_key),
                  weight = VALUES(weight)
                """,
                alias,
            )
            alias_written += 1

        return {
            "vertical_norm": vertical,
            "concepts_processed": concept_written,
            "aliases_processed": alias_written,
        }


def _normalize_vertical(vertical_norm: str) -> str:
    value = str(vertical_norm or "generic").strip().lower()
    return value or "generic"


def _seed_concepts(vertical: str) -> List[Dict[str, Any]]:
    if vertical == "education":
        return [
            _concept(vertical, "STUDENT_ID", "Student ID", "Unique student identifier.", "identifier", None, "student", 0, True, True, False, True, False),
            _concept(vertical, "SCHOOL_ID", "School ID", "Unique school identifier.", "identifier", None, "school", 0, True, True, False, True, False),
            _concept(vertical, "LEA_ID", "LEA ID", "Unique local education agency identifier.", "identifier", None, "lea", 0, True, True, False, True, False),
            _concept(vertical, "COURSE_ID", "Course ID", "Unique course identifier.", "identifier", None, "course", 0, True, True, False, True, False),
            _concept(vertical, "SECTION_ID", "Section ID", "Unique section identifier.", "identifier", None, "section", 0, True, True, False, True, False),
            _concept(vertical, "COURSE_CODE", "Course Code", "Assigned course code.", "reference", None, "course", 0, True, True, False, False, False),
            _concept(vertical, "STATE_COURSE_CODE", "State Course Code", "State-assigned course code.", "reference", None, "course", 0, True, True, False, False, False),
            _concept(vertical, "SCHOOL_YEAR", "School Year", "Academic school year.", "time", "time.year", None, 0, True, True, False, False, False),
            _concept(vertical, "ENROLLMENT_COUNT", "Enrollment Count", "Count of enrolled students.", "metric", "measure.count", "student", 1, False, False, True, False, True),
            _concept(vertical, "STUDENT_GRADE_LEVEL", "Student Grade Level", "Student grade level dimension.", "dimension", "group_by.grade", "student", 1, True, True, False, False, False),
            _concept(vertical, "TERM", "Term", "Academic term.", "time", "time.term", None, 1, True, True, False, False, False),
            _concept(
                vertical,
                "SEMESTER_SPRING_FLAG",
                "Semester Spring Flag",
                "Boolean indicator for spring semester rows.",
                "flag",
                "time.term.spring",
                None,
                1,
                True,
                True,
                False,
                False,
                False,
            ),
            _concept(
                vertical,
                "SEMESTER_FALL_FLAG",
                "Semester Fall Flag",
                "Boolean indicator for fall semester rows.",
                "flag",
                "time.term.fall",
                None,
                1,
                True,
                True,
                False,
                False,
                False,
            ),
            _concept(
                vertical,
                "SEMESTER_YEAR_ROUND_FLAG",
                "Semester Year Round Flag",
                "Boolean indicator for year-round semester rows.",
                "flag",
                "time.term.year_round",
                None,
                1,
                True,
                True,
                False,
                False,
                False,
            ),
            _concept(vertical, "CITY", "City", "City geography.", "geography", "geography.city", None, 1, True, True, False, False, False),
            _concept(vertical, "COUNTY", "County", "County geography.", "geography", "geography.county", None, 2, True, True, False, False, False),
            _concept(vertical, "STATE", "State", "State geography.", "geography", "geography.state", None, 3, True, True, False, False, False),
            _concept(vertical, "ZIP_CODE", "ZIP Code", "Zip/postal code geography.", "geography", "geography.zip", None, 0, True, True, False, False, False),
            _concept(vertical, "COURSE_TITLE", "Course Title", "Course title attribute.", "attribute", None, "course", 0, True, True, False, False, False),
            _concept(vertical, "COURSE_DESCRIPTION", "Course Description", "Course description attribute.", "attribute", None, "course", 0, True, True, False, False, False),
            _concept(vertical, "SCHOOL_NAME", "School Name", "School name attribute.", "attribute", None, "school", 0, True, True, False, False, False),
        ]

    if vertical == "generic":
        return [
            _concept(vertical, "CITY", "City", "City geography.", "geography", "geography.city", None, 1, True, True, False, False, False),
            _concept(vertical, "STATE", "State", "State geography.", "geography", "geography.state", None, 3, True, True, False, False, False),
            _concept(vertical, "DATE", "Date", "Calendar date.", "time", "time.date", None, 2, True, True, False, False, False),
        ]

    return []


def _seed_aliases(vertical: str) -> List[Dict[str, Any]]:
    if vertical != "education":
        return []

    return [
        _alias(vertical, "k_student", "STUDENT_ID", "exact", 1.0),
        _alias(vertical, "k_student", "STUDENT_ID", "normalized", 0.95),
        _alias(vertical, "^k_student$", "STUDENT_ID", "regex", 0.95),
        _alias(vertical, "student_id", "STUDENT_ID", "exact", 1.0),
        _alias(vertical, "student_id", "STUDENT_ID", "normalized", 0.95),
        _alias(vertical, "student", "STUDENT_ID", "suffix", 0.75),
        _alias(vertical, "student enrollment", "ENROLLMENT_COUNT", "exact", 1.4),
        _alias(vertical, "enrolled students", "ENROLLMENT_COUNT", "contains", 1.25),
        _alias(vertical, "enrollment", "ENROLLMENT_COUNT", "contains", 1.2),
        _alias(vertical, "grade level", "STUDENT_GRADE_LEVEL", "contains", 1.2),
        _alias(vertical, "grade", "STUDENT_GRADE_LEVEL", "contains", 0.95),
        _alias(vertical, "^(.+)_id$", "DYNAMIC_IDENTIFIER", "regex", 0.6),
        _alias(vertical, "k_school", "SCHOOL_ID", "exact", 1.0),
        _alias(vertical, "k_school", "SCHOOL_ID", "normalized", 0.95),
        _alias(vertical, "^k_school$", "SCHOOL_ID", "regex", 0.95),
        _alias(vertical, "school_id", "SCHOOL_ID", "exact", 1.0),
        _alias(vertical, "school", "SCHOOL_ID", "prefix", 0.8),
        _alias(vertical, "k_lea", "LEA_ID", "exact", 1.0),
        _alias(vertical, "k_lea", "LEA_ID", "normalized", 0.95),
        _alias(vertical, "^k_lea$", "LEA_ID", "regex", 0.95),
        _alias(vertical, "lea_id", "LEA_ID", "exact", 1.0),
        _alias(vertical, "k_course", "COURSE_ID", "exact", 1.0),
        _alias(vertical, "^k_(.+)$", "DYNAMIC_IDENTIFIER", "regex", 0.65),
        _alias(vertical, "course_id", "COURSE_ID", "exact", 1.0),
        _alias(vertical, "course_code", "COURSE_CODE", "exact", 1.0),
        _alias(vertical, "state_course_code", "STATE_COURSE_CODE", "exact", 1.0),
        _alias(vertical, "school_year", "SCHOOL_YEAR", "exact", 1.0),
        _alias(vertical, "spring semester", "SEMESTER_SPRING_FLAG", "contains", 1.1),
        _alias(vertical, "spring term", "SEMESTER_SPRING_FLAG", "contains", 1.1),
        _alias(vertical, "is_spring", "SEMESTER_SPRING_FLAG", "contains", 1.1),
        _alias(vertical, "is_spring_block", "SEMESTER_SPRING_FLAG", "exact", 1.25),
        _alias(vertical, "fall semester", "SEMESTER_FALL_FLAG", "contains", 1.1),
        _alias(vertical, "fall term", "SEMESTER_FALL_FLAG", "contains", 1.1),
        _alias(vertical, "is_fall", "SEMESTER_FALL_FLAG", "contains", 1.1),
        _alias(vertical, "is_fall_block", "SEMESTER_FALL_FLAG", "exact", 1.25),
        _alias(vertical, "year round", "SEMESTER_YEAR_ROUND_FLAG", "contains", 1.1),
        _alias(vertical, "year-round", "SEMESTER_YEAR_ROUND_FLAG", "contains", 1.1),
        _alias(vertical, "is_year_round", "SEMESTER_YEAR_ROUND_FLAG", "contains", 1.1),
        _alias(vertical, "is_year_round_block", "SEMESTER_YEAR_ROUND_FLAG", "exact", 1.25),
        _alias(vertical, "name_of_county", "COUNTY", "contains", 0.95),
        _alias(vertical, "county", "COUNTY", "contains", 0.9),
        _alias(vertical, "city", "CITY", "contains", 0.9),
        _alias(vertical, "zip", "ZIP_CODE", "contains", 0.9),
        _alias(vertical, "postal", "ZIP_CODE", "contains", 0.85),
    ]


def _concept(
    vertical: str,
    concept_key: str,
    name: str,
    description: str,
    semantic_type: str,
    sub_type: str | None,
    entity: str | None,
    granularity_rank: int,
    filter_allowed: bool,
    group_by_allowed: bool,
    aggregation_allowed: bool,
    is_identifier: bool,
    is_metric: bool,
) -> Dict[str, Any]:
    return {
        "vertical_norm": vertical,
        "concept_key": normalize_concept_key(concept_key),
        "name": name,
        "description": description,
        "semantic_type": semantic_type,
        "sub_type": sub_type,
        "entity": entity,
        "granularity_rank": int(granularity_rank),
        "filter_allowed": 1 if filter_allowed else 0,
        "group_by_allowed": 1 if group_by_allowed else 0,
        "aggregation_allowed": 1 if aggregation_allowed else 0,
        "is_identifier": 1 if is_identifier else 0,
        "is_metric": 1 if is_metric else 0,
        "display_priority": 0,
        "sensitive": 0,
        "status": "active",
    }


def _alias(vertical: str, alias_key: str, concept_key: str, match_kind: str, weight: float) -> Dict[str, Any]:
    return {
        "vertical_norm": vertical,
        "alias_key": str(alias_key).strip().lower(),
        "concept_key": normalize_concept_key(concept_key),
        "match_kind": str(match_kind).strip().lower(),
        "weight": float(weight),
    }

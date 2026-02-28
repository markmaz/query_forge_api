from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


SubjectEntity = Literal[
    "student",
    "staff",
    "parent",
    "school",
    "district",
    "lea",
    "section",
    "course",
    "assessment",
    "discipline_incident",
    "attendance_event",
    "calendar_event",
    "unknown",
]

TopicName = Literal[
    "demographics",
    "enrollment",
    "attendance",
    "discipline",
    "grades",
    "assessments",
    "scheduling",
    "staffing",
    "calendar",
]


class Tier2NameSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["first", "last", "full", "unknown"] = "unknown"
    value: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2ValueSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2CourseSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    code: Optional[str] = None
    subject: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2SectionSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    name: Optional[str] = None
    period: Optional[str] = None
    term: Optional[str] = None
    teacher_name: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2CalendarSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: Optional[str] = None
    date_range: Optional[str] = None
    school_year: Optional[str] = None
    term_name: Optional[str] = None
    event_type: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2AttendanceSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Optional[str] = None
    minutes: Optional[str] = None
    excuse: Optional[str] = None
    date: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2DisciplineSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    incident_type: Optional[str] = None
    action: Optional[str] = None
    duration_days: Optional[str] = None
    severity: Optional[str] = None
    date: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2AssessmentSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    type: Optional[str] = None
    score: Optional[str] = None
    performance_level: Optional[str] = None
    proficiency: Optional[str] = None
    date: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2GradesSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    student_grade_level: Optional[str] = None
    course_grade: Optional[str] = None
    gpa: Optional[str] = None
    credits: Optional[str] = None
    grading_period: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2Slots(BaseModel):
    model_config = ConfigDict(extra="ignore")

    names: List[Tier2NameSlot] = Field(default_factory=list)
    school: List[Tier2ValueSlot] = Field(default_factory=list)
    district: List[Tier2ValueSlot] = Field(default_factory=list)
    race: List[Tier2ValueSlot] = Field(default_factory=list)
    grade: List[Tier2ValueSlot] = Field(default_factory=list)
    country: List[Tier2ValueSlot] = Field(default_factory=list)
    state: List[Tier2ValueSlot] = Field(default_factory=list)
    negations: List[Tier2ValueSlot] = Field(default_factory=list)
    course: List[Tier2CourseSlot] = Field(default_factory=list)
    section: List[Tier2SectionSlot] = Field(default_factory=list)
    calendar: List[Tier2CalendarSlot] = Field(default_factory=list)
    attendance: List[Tier2AttendanceSlot] = Field(default_factory=list)
    discipline: List[Tier2DisciplineSlot] = Field(default_factory=list)
    assessments: List[Tier2AssessmentSlot] = Field(default_factory=list)
    grades: List[Tier2GradesSlot] = Field(default_factory=list)


class Tier2Entities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject_entity: SubjectEntity = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Tier2Operators(BaseModel):
    model_config = ConfigDict(extra="ignore")

    negation: bool = False
    comparators: List[Dict[str, Any]] = Field(default_factory=list)


class Tier2Intent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: Optional[str] = None
    scores: Dict[str, float] = Field(default_factory=dict)


class Tier2Extraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt: str
    entities: Tier2Entities = Field(default_factory=Tier2Entities)
    topic: List[TopicName] = Field(default_factory=list)
    slots: Tier2Slots = Field(default_factory=Tier2Slots)
    operators: Tier2Operators = Field(default_factory=Tier2Operators)
    intent: Tier2Intent = Field(default_factory=Tier2Intent)
    domain_hint: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)


def empty_extraction(prompt: str, *, warnings: Optional[List[str]] = None) -> Tier2Extraction:
    return Tier2Extraction(prompt=prompt, warnings=list(warnings or []))

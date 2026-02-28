from __future__ import annotations

import re
from typing import Dict, List

from app.nlp.tier2_spacy.schema import TopicName

_TOPIC_PATTERNS: Dict[TopicName, List[str]] = {
    "attendance": [
        r"\babsent\b",
        r"\btardy\b",
        r"\bpresent\b",
        r"\battendance\b",
        r"\bminutes\s+missed\b",
    ],
    "discipline": [
        r"\bsuspension\b",
        r"\bexpulsion\b",
        r"\bincident\b",
        r"\breferral\b",
        r"\bdiscipline\b",
    ],
    "grades": [
        r"\bgpa\b",
        r"\bgrades?\b",
        r"\breport\s+card\b",
        r"\bcredits?\b",
        r"\bgrading\s+period\b",
    ],
    "assessments": [
        r"\btest\b",
        r"\bassessment\b",
        r"\bscore\b",
        r"\bproficiency\b",
        r"\bbenchmark\b",
        r"\bact\b",
        r"\bsat\b",
    ],
    "scheduling": [
        r"\bsection\b",
        r"\bperiod\b",
        r"\broster\b",
        r"\bcourse\b",
        r"\bclass\b",
        r"\bteacher\b",
    ],
    "calendar": [
        r"\bcalendar\b",
        r"\bholiday\b",
        r"\bschool\s+day\b",
        r"\bevent\b",
        r"\bterm\b",
        r"\bsemester\b",
        r"\bdate\s+range\b",
    ],
    "demographics": [
        r"\brace\b",
        r"\bethnicity\b",
        r"\bborn\b",
        r"\bcountry\b",
        r"\bgender\b",
        r"\bage\b",
    ],
    "enrollment": [
        r"\benroll\w*\b",
        r"\bregistered\b",
        r"\bactive\s+students?\b",
    ],
    "staffing": [
        r"\bstaff\b",
        r"\bteacher\b",
        r"\bprincipal\b",
    ],
}

_SUBJECT_PATTERNS = {
    "student": [r"\bstudent\b", r"\bstudents\b", r"\bkid\b", r"\bkids\b", r"\bpupil\b", r"\blearner\b"],
    "staff": [r"\bstaff\b", r"\bteacher\b", r"\bteachers\b", r"\binstructor\b"],
    "parent": [r"\bparent\b", r"\bparents\b", r"\bguardian\b"],
    "school": [r"\bschool\b", r"\bschools\b"],
    "district": [r"\bdistrict\b", r"\blea\b", r"\bcounty\b"],
    "section": [r"\bsection\b", r"\broster\b"],
    "course": [r"\bcourse\b", r"\bclass\b", r"\balgebra\b", r"\bgeometry\b"],
    "assessment": [r"\bassessment\b", r"\btest\b", r"\bexam\b", r"\bbenchmark\b"],
    "discipline_incident": [r"\bdiscipline\b", r"\bincident\b", r"\bsuspension\b", r"\bexpulsion\b"],
    "attendance_event": [r"\battendance\b", r"\babsent\b", r"\btardy\b"],
    "calendar_event": [r"\bcalendar\b", r"\bholiday\b", r"\bterm\b", r"\bsemester\b"],
}


def route_topics(prompt: str) -> Dict[str, object]:
    text = str(prompt or "").strip().lower()
    if text == "":
        return {"topic_scores": {}, "subject_entity_hint": "unknown", "topic": []}

    topic_scores: Dict[str, float] = {}
    for topic, patterns in _TOPIC_PATTERNS.items():
        score = 0.0
        for pattern in patterns:
            if re.search(pattern, text):
                score += 1.0
        if score > 0:
            topic_scores[topic] = round(score / max(1.0, float(len(patterns) / 2.0)), 4)

    subject_scores: Dict[str, float] = {}
    for subject, patterns in _SUBJECT_PATTERNS.items():
        score = 0.0
        for pattern in patterns:
            if re.search(pattern, text):
                score += 1.0
        if score > 0:
            subject_scores[subject] = score

    subject_entity_hint = "unknown"
    if subject_scores:
        subject_entity_hint = max(subject_scores.items(), key=lambda item: item[1])[0]

    top_topics = [
        topic for topic, _ in sorted(topic_scores.items(), key=lambda item: item[1], reverse=True)[:3]
    ]
    return {
        "topic_scores": topic_scores,
        "subject_entity_hint": subject_entity_hint,
        "topic": top_topics,
    }

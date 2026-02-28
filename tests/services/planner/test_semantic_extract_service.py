from __future__ import annotations

from app.services.planner.semantic_extract_service import SemanticExtractService


def test_extract_slots_maps_labels_and_dedupes() -> None:
    def _fake_extractor(_prompt: str):
        return {
            "normalized_text": "Prompt",
            "by_label": {
                "METRIC": ["chronically absent", "Chronically Absent"],
                "DIMENSION": ["school"],
                "SUBGROUP": ["English Learners", "english learners"],
                "TIME_RANGE": ["this year"],
                "ORG_SCHOOL": ["Holden Elementary"],
                "ORG_DISTRICT": ["Davidson County Schools"],
            },
            "ents": [],
            "warnings": [],
        }

    svc = SemanticExtractService(extractor=_fake_extractor)
    slots = svc.extract_slots("any")
    assert slots == {
        "metric": ["chronically absent"],
        "dimensions": ["school"],
        "subgroups": ["English Learners"],
        "time_ranges": ["this year"],
        "org_schools": ["Holden Elementary"],
        "org_districts": ["Davidson County Schools"],
    }

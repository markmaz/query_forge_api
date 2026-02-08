from __future__ import annotations

from datetime import datetime

from app.services.embedding.domain_embedding_service import (
    _parse_json_list,
    build_domain_payload,
    build_domain_point_id,
)


def test_parse_json_list_handles_strings_and_bytes() -> None:
    assert _parse_json_list('["a", "b"]') == ["a", "b"]
    assert _parse_json_list(b'["c"]') == ["c"]
    assert _parse_json_list("") == []
    assert _parse_json_list(None) == []
    assert _parse_json_list("not json") == []


def test_build_domain_point_id() -> None:
    point_id = build_domain_point_id("ws1", 42)
    assert isinstance(point_id, str)
    assert len(point_id) == 36


def test_build_domain_payload_schema() -> None:
    row = {
        "workspace_id": "ws1",
        "domain_id": 7,
        "domain_name": "Attendance",
        "domain_kind": "Attendance",
        "domain_is_active": 1,
        "summary": "Student attendance events.",
        "keywords": '["attendance", "absences"]',
        "entities": '["student", "school"]',
        "attributes": None,
        "metrics": b'["attendance_rate"]',
        "synonyms": [
            {"term": "absence", "means": ["not present"]},
        ],
        "acronyms": '[{"abbr": "ADA", "expansion": "Average Daily Attendance"}]',
        "notes": "Notes",
        "content_hash": "abc123",
        "updated_at": datetime(2024, 1, 2, 3, 4, 5),
    }
    table_rows = [
        {
            "workspace_table_id": 101,
            "is_primary": 1,
            "role": "FACT",
            "relation_kind": "JOIN",
            "sort_order": 0,
            "table_alias": "att",
            "filter_mode": "AUTO",
            "cardinality": "MANY",
        }
    ]

    payload = build_domain_payload(row, table_rows, [101])
    required = {
        "type",
        "workspace_id",
        "domain_id",
        "domain_name",
        "domain_kind",
        "is_active",
        "workspace_table_ids",
        "workspace_tables",
        "summary",
        "keywords",
        "entities",
        "attributes",
        "metrics",
        "synonyms",
        "acronyms",
        "notes",
        "content_hash",
        "updated_at",
    }
    assert required.issubset(payload.keys())
    assert payload["type"] == "domain"
    assert payload["workspace_id"] == "ws1"
    assert payload["domain_id"] == 7
    assert payload["external_id"] == "domain:ws1:7"
    assert payload["keywords"] == ["attendance", "absences"]
    assert payload["metrics"] == ["attendance_rate"]
    assert payload["workspace_table_ids"] == [101]
    assert payload["updated_at"] == "2024-01-02T03:04:05"

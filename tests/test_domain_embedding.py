from __future__ import annotations

from datetime import datetime

import pytest

from app.services.embedding import domain_embedding_service
from app.services.embedding.domain_embedding_service import (
    DomainEmbeddingService,
    _parse_json_list,
    build_domain_payload,
    build_domain_point_id,
)
from tests._support.fakes import FakeForgeQueryPort


class _FakeQdrant:
    def ensure_collection(self, name: str, vector_size: int) -> None:
        del name, vector_size

    def retrieve_payloads(self, ids):
        del ids
        return {}

    def upsert_points(self, points, *, wait: bool = True) -> int:
        del wait
        return len(list(points))


class _FakeModel:
    def encode(self, texts, *, normalize: bool = True, batch_size: int = 64):
        del texts, normalize, batch_size
        return []


def test_parse_json_list_handles_strings_and_bytes() -> None:
    assert _parse_json_list('["a", "b"]') == ["a", "b"]
    assert _parse_json_list(b'["c"]') == ["c"]
    assert _parse_json_list("") == []
    assert _parse_json_list(None) == []
    assert _parse_json_list("not json") == []


def test_parse_json_list_surfaces_unexpected_json_loader_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_raw):
        raise AssertionError("unexpected json loader failure")

    monkeypatch.setattr(domain_embedding_service.json, "loads", _boom)

    with pytest.raises(AssertionError, match="unexpected json loader failure"):
        _parse_json_list('["a"]')


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


def test_upsert_domain_profiles_records_expected_payload_build_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "workspace_id": "ws1",
                "domain_id": 7,
                "embedding_text": "attendance profile",
                "content_hash": "abc123",
            }
        ],
        [],
    ]
    service = DomainEmbeddingService(sql=sql, qdrant=_FakeQdrant(), model=_FakeModel())

    def _bad_payload(*args, **kwargs):
        del args, kwargs
        raise ValueError("bad payload")

    monkeypatch.setattr(domain_embedding_service, "build_domain_payload", _bad_payload)

    result = service.upsert_domain_profiles("ws1", force=True)

    assert result["upserted"] == 0
    assert result["errors"] == ["domain_id=7: bad payload"]


def test_upsert_domain_profiles_surfaces_unexpected_payload_build_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "workspace_id": "ws1",
                "domain_id": 7,
                "embedding_text": "attendance profile",
                "content_hash": "abc123",
            }
        ],
        [],
    ]
    service = DomainEmbeddingService(sql=sql, qdrant=_FakeQdrant(), model=_FakeModel())

    def _boom(*args, **kwargs):
        del args, kwargs
        raise AssertionError("unexpected payload bug")

    monkeypatch.setattr(domain_embedding_service, "build_domain_payload", _boom)

    with pytest.raises(AssertionError, match="unexpected payload bug"):
        service.upsert_domain_profiles("ws1", force=True)

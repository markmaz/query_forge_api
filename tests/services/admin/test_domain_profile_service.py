from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from app.exceptions.forge_error import ForgeError
from app.models.domain_profile import (
    DomainProfileCreateRequest,
    DomainProfileUpdateRequest,
    compute_content_hash,
)
from app.services.admin.domain_profile_service import DomainProfileService


_SAMPLE_ROW = {
    "id": 1,
    "workspace_id": "ws-1",
    "domain_id": 4,
    "summary": "Schools and districts",
    "keywords": json.dumps(["schools", "districts"]),
    "entities": json.dumps(["school", "district"]),
    "metrics": json.dumps(["enrollment_count"]),
    "attributes": json.dumps(["school_id", "district_id"]),
    "synonyms": json.dumps([{"term": "org", "means": ["organization"]}]),
    "acronyms": json.dumps([{"abbr": "LEA", "expansion": "Local Education Agency"}]),
    "notes": "Used for grouping.",
    "embedding_text": "Domain: Schools",
    "content_hash": compute_content_hash("Domain: Schools"),
    "embedding_model": None,
    "embedded_at": None,
    "created_at": "2026-01-01 00:00:00",
    "updated_at": None,
    "domain_name": "Schools",
}


class _FakeSQL:
    def __init__(
        self,
        *,
        query_rows: Optional[List[Dict[str, Any]]] = None,
        fail_write: bool = False,
    ) -> None:
        self._query_rows = query_rows if query_rows is not None else []
        self._fail_write = fail_write
        self.last_write_query: Optional[str] = None
        self.last_write_params: Optional[Dict[str, Any]] = None
        self._call_count = 0

    def execute_query_mappings(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        self._call_count += 1
        return list(self._query_rows)

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        if self._fail_write:
            raise RuntimeError("write failed")
        self.last_write_query = query
        self.last_write_params = params
        return 1

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Tuple]:
        return []


class _FakeSQLForCreate:
    """Returns empty on first call (check existence), then returns row on second (re-fetch)."""
    def __init__(self, row: Dict[str, Any]) -> None:
        self._row = row
        self._call_count = 0
        self.last_write_query: Optional[str] = None
        self.last_write_params: Optional[Dict[str, Any]] = None

    def execute_query_mappings(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        self._call_count += 1
        if self._call_count == 1:
            return []
        return [self._row]

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        self.last_write_query = query
        self.last_write_params = params
        return 1


class _FakeSQLForUpdate:
    """Returns row on first call (exists check), then returns updated row on second (re-fetch)."""
    def __init__(self, row: Dict[str, Any], updated_row: Optional[Dict[str, Any]] = None) -> None:
        self._row = row
        self._updated_row = updated_row or row
        self._call_count = 0

    def execute_query_mappings(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        self._call_count += 1
        if self._call_count == 1:
            return [self._row]
        return [self._updated_row]

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        return 1


# ---- list ----

def test_list_profiles_returns_rows():
    svc = DomainProfileService(sql=_FakeSQL(query_rows=[_SAMPLE_ROW]))
    result = svc.list_profiles("ws-1")
    assert len(result) == 1
    assert result[0]["domain_id"] == 4
    assert result[0]["domain_name"] == "Schools"


def test_list_profiles_empty():
    svc = DomainProfileService(sql=_FakeSQL(query_rows=[]))
    result = svc.list_profiles("ws-1")
    assert result == []


def test_list_profiles_requires_workspace():
    svc = DomainProfileService(sql=_FakeSQL())
    with pytest.raises(ForgeError) as exc_info:
        svc.list_profiles("")
    assert exc_info.value.status_code == 400


# ---- get ----

def test_get_profile_found():
    svc = DomainProfileService(sql=_FakeSQL(query_rows=[_SAMPLE_ROW]))
    result = svc.get_profile("ws-1", 4)
    assert result["domain_id"] == 4
    assert result["keywords"] == ["schools", "districts"]


def test_get_profile_not_found():
    svc = DomainProfileService(sql=_FakeSQL(query_rows=[]))
    with pytest.raises(ForgeError) as exc_info:
        svc.get_profile("ws-1", 999)
    assert exc_info.value.status_code == 404


# ---- create ----

def test_create_profile_success():
    fake_sql = _FakeSQLForCreate(_SAMPLE_ROW)
    svc = DomainProfileService(sql=fake_sql)
    req = DomainProfileCreateRequest(
        workspace_id="ws-1",
        domain_id=4,
        summary="Schools and districts",
        keywords=["schools", "districts"],
    )
    result = svc.create_profile(req)
    assert result["domain_id"] == 4
    assert fake_sql.last_write_query is not None
    assert "INSERT INTO" in fake_sql.last_write_query


def test_create_profile_conflict():
    svc = DomainProfileService(sql=_FakeSQL(query_rows=[_SAMPLE_ROW]))
    req = DomainProfileCreateRequest(
        workspace_id="ws-1",
        domain_id=4,
        summary="duplicate",
    )
    with pytest.raises(ForgeError) as exc_info:
        svc.create_profile(req)
    assert exc_info.value.status_code == 409


def test_create_profile_generates_embedding_text():
    fake_sql = _FakeSQLForCreate(_SAMPLE_ROW)
    svc = DomainProfileService(sql=fake_sql)
    req = DomainProfileCreateRequest(
        workspace_id="ws-1",
        domain_id=4,
        summary="Test summary",
        keywords=["k1", "k2"],
    )
    svc.create_profile(req)
    assert fake_sql.last_write_params is not None
    assert "Test summary" in fake_sql.last_write_params["embedding_text"]


# ---- update ----

def test_update_profile_success():
    updated = dict(_SAMPLE_ROW)
    updated["summary"] = "Updated summary"
    svc = DomainProfileService(sql=_FakeSQLForUpdate(_SAMPLE_ROW, updated))
    req = DomainProfileUpdateRequest(summary="Updated summary")
    result = svc.update_profile("ws-1", 4, req)
    assert result["summary"] == "Updated summary"


def test_update_profile_not_found():
    svc = DomainProfileService(sql=_FakeSQL(query_rows=[]))
    req = DomainProfileUpdateRequest(summary="nope")
    with pytest.raises(ForgeError) as exc_info:
        svc.update_profile("ws-1", 999, req)
    assert exc_info.value.status_code == 404


# ---- delete ----

def test_delete_profile_success():
    fake_sql = _FakeSQLForUpdate(_SAMPLE_ROW)
    svc = DomainProfileService(sql=fake_sql)
    result = svc.delete_profile("ws-1", 4)
    assert result["deleted"] is True


def test_delete_profile_not_found():
    svc = DomainProfileService(sql=_FakeSQL(query_rows=[]))
    with pytest.raises(ForgeError) as exc_info:
        svc.delete_profile("ws-1", 999)
    assert exc_info.value.status_code == 404


# ---- model tests ----

def test_compute_content_hash_deterministic():
    h1 = compute_content_hash("hello")
    h2 = compute_content_hash("hello")
    h3 = compute_content_hash("world")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_create_request_auto_generates_embedding_text():
    req = DomainProfileCreateRequest(
        workspace_id="ws-1",
        domain_id=1,
        summary="A test domain",
        keywords=["alpha", "beta"],
    )
    assert req.embedding_text is not None
    assert "A test domain" in req.embedding_text
    assert "alpha" in req.embedding_text

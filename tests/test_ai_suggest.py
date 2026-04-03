from __future__ import annotations

from typing import Any, Dict, List

import pytest
from flask import Flask
from flask_restx import Api

from app.decorators import security
from app.exceptions.forge_error import ForgeError
import app.routes.ai as ai_routes
from app.routes.ai import ai_ns
from app.routes import request_helpers as _route_utils
from app.services.ai_suggest import AISuggestService
import app.services.ai_suggest.domain_seeder as domain_seeder
import app.services.ai_suggest.edit_inspector as edit_inspector
import app.services.ai_suggest.prompt_analysis as prompt_analysis
import app.services.ai_suggest.vllm_client as vllm_client


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise vllm_client.requests.HTTPError(f"status={self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._payload


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        VLLM_BASE_URL="http://localhost:8000",
        VLLM_MODEL="qwen25-7b",
        VLLM_TIMEOUT=60,
    )
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        _route_utils.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )

    def _bypass_semantic(*args, **kwargs):
        raise RuntimeError("semantic bridge bypassed for test")

    monkeypatch.setattr(ai_routes, "_plan_response_as_suggest", _bypass_semantic)

    api = Api(app)
    api.add_namespace(ai_ns, path="/api/ai")
    return app.test_client()


def _request_body() -> Dict[str, Any]:
    return {
        "mode": "columns",
        "prompt": "Select student school year",
        "currentSqlJson": None,
        "domainContext": {
            "selectedDomainId": 10,
            "domainCandidates": [
                {"domainId": 10, "name": "Students", "description": "Student enrollment records"}
            ],
        },
        "candidates": {
            "tables": [{"tableId": 1, "tableName": "students", "score": 0.95}],
            "columns": [
                {
                    "modelColumnId": 351,
                    "columnName": "school_year",
                    "workspaceTableId": 24,
                    "modelTableId": 101,
                    "modelTableName": "students",
                    "label": "School Year",
                    "description": "School year",
                    "dataType": "int",
                    "score": 0.91,
                },
                {
                    "modelColumnId": 352,
                    "columnName": "student_id",
                    "workspaceTableId": 24,
                    "modelTableId": 101,
                    "modelTableName": "students",
                    "label": "Student Id",
                    "description": "Student identifier",
                    "dataType": "string",
                    "score": 0.88,
                },
            ],
        },
    }


def _headers(workspace_id: str = "ws-1") -> Dict[str, str]:
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": workspace_id,
    }


def _retrieval_payload() -> Dict[str, Any]:
    return {
        "results": {
            "domains": [
                {"domainId": 10, "domainName": "Students", "domainKind": "K12", "score": 0.92, "reasons": ["vector_similarity"]}
            ],
            "tables": [
                {"tableName": "students", "modelTableId": 101, "score": 0.87, "reasons": ["vector_similarity"]}
            ],
            "columns": [
                {
                    "tableName": "students",
                    "columnName": "school_year",
                    "description": "School year of enrollment",
                    "dataType": "int",
                    "score": 0.93,
                    "reasons": ["vector_similarity", "match.name_contains"],
                }
            ],
        }
    }


def _edit_by_op(edits: List[Dict[str, Any]], op: str) -> Dict[str, Any]:
    for edit in edits:
        if edit.get("op") == op:
            return edit
    raise AssertionError(f"Missing edit op={op}: {edits}")


def test_suggest_valid_json_first_attempt(client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []

    valid_content = (
        '{"edits":[{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":null}],'
        '"explanation":"Added school year selection","confidence":0.92}'
    )

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse({"choices": [{"message": {"content": valid_content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 1
    assert data["debug"]["model"] == "qwen25-7b"
    assert len(data["edits"]) == 2
    assert _edit_by_op(data["edits"], "setDomain")["domainId"] == 10
    assert _edit_by_op(data["edits"], "addSelect")["col"]["columnName"] == "school_year"
    assert data["sqlJson"]["version"] == 1
    assert data["sqlJson"]["domainId"] == 10
    assert calls[0]["url"] == "http://localhost:8000/v1/chat/completions"
    assert '"workspaceId":"ws-1"' in calls[0]["json"]["messages"][1]["content"]
    assert calls[0]["json"]["temperature"] == 0.2
    assert calls[0]["json"]["top_p"] == 0.8


def test_suggest_normalizes_operation_and_missing_top_level_fields(client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []
    content = '{"edits":[{"operation":"addSelect","columnKey":"students.school_year","alias":null}]}'

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert len(calls) == 1
    assert data["debug"]["attempts"] == 1
    assert _edit_by_op(data["edits"], "setDomain")["domainId"] == 10
    assert _edit_by_op(data["edits"], "addSelect")["col"]["columnName"] == "school_year"
    assert data["explanation"] == ""
    assert data["confidence"] == 0.5
    assert data["sqlJson"]["version"] == 1


def test_suggest_normalization_drops_invalid_ops(client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []
    content = (
        '{"edits":['
        '{"operation":"badOp","columnKey":"students.bad_col"},'
        '{"operation":"addSelect","columnKey":"students.school_year","alias":null}'
        '],"explanation":123,"confidence":2}'
    )

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert len(calls) == 1
    assert data["debug"]["attempts"] == 1
    assert len(data["edits"]) == 2
    assert _edit_by_op(data["edits"], "setDomain")["domainId"] == 10
    assert _edit_by_op(data["edits"], "addSelect")["op"] == "addSelect"
    assert data["confidence"] == 1.0
    assert data["explanation"] == "123"
    assert data["sqlJson"]["version"] == 1


def test_suggest_normalizes_columnkey_to_col_for_filter_and_aggregate(client, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        '{"edits":['
        '{"operation":"addFilter","columnKey":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"operator":"contains","value":"2024"},'
        '{"operation":"addAggregate","func":"count","columnKey":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}'
        '],"explanation":"ok","confidence":0.7}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 1
    assert len(data["edits"]) == 3
    assert _edit_by_op(data["edits"], "setDomain")["domainId"] == 10
    assert _edit_by_op(data["edits"], "addFilter")["col"]["columnName"] == "school_year"
    assert _edit_by_op(data["edits"], "addFilter")["operator"] == "contains"
    assert _edit_by_op(data["edits"], "addAggregate")["col"]["columnName"] == "student_id"
    assert data["sqlJson"]["filters"]["children"][0]["op"] == "contains"
    assert data["sqlJson"]["aggs"]["metrics"][0]["fn"] == "count"


def test_suggest_strips_extra_keys_inside_col_before_validation(client, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        '{"edits":[{"op":"addSelect","col":{"modelColumnId":87,"columnName":"available_credits","workspaceTableId":9,'
        '"modelTableId":10,"modelTableName":"dim_course_section"},"alias":"available_credits"}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 1
    col = _edit_by_op(data["edits"], "addSelect")["col"]
    assert col["modelColumnId"] == 87
    assert col["columnName"] == "available_credits"
    assert col["workspaceTableId"] == 9
    assert "modelTableId" not in col
    assert "modelTableName" not in col


def test_suggest_drops_edit_when_col_missing_column_name_after_sanitize(client, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        '{"edits":[{"op":"addSelect","col":{"modelColumnId":87,"workspaceTableId":9,"modelTableId":10}}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 1
    assert data["edits"] == []


def test_suggest_invalid_col_type_still_fails_validation(client, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        '{"edits":[{"op":"addSelect","col":"students.school_year","alias":"school_year"}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 500
    data = response.get_json()
    assert data["error"] == "Invalid model response"
    assert data["details"]["type"] == "schema_validation_error"
    assert data["details"]["attempt"] == 2


def test_suggest_accepts_equals_operator_enum(client, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        '{"edits":[{"op":"addFilter","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},'
        '"operator":"equals","value":2024}],"explanation":"ok","confidence":0.66}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert _edit_by_op(data["edits"], "addFilter")["operator"] == "equals"
    assert data["sqlJson"]["filters"]["children"][0]["op"] == "equals"


def test_suggest_uses_header_workspace_over_body_workspace(client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []
    valid_content = '{"edits":[],"explanation":"ok","confidence":0.5}'

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse({"choices": [{"message": {"content": valid_content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    body = _request_body()
    body["workspaceId"] = "tampered-ws"
    response = client.post("/api/ai/suggest", json=body, headers=_headers("ws-1"))

    assert response.status_code == 200
    user_prompt = calls[0]["json"]["messages"][1]["content"]
    assert '"workspaceId":"ws-1"' in user_prompt
    assert '"workspaceId":"tampered-ws"' not in user_prompt


def test_suggest_retries_once_after_invalid_json(client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []
    responses = [
        _FakeResponse({"choices": [{"message": {"content": "not-json"}}]}),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[],"explanation":"Need metric details to continue","confidence":0.41}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert len(calls) == 2
    second_messages = calls[1]["json"]["messages"]
    assert "Use key 'op' (NOT 'operation')" in second_messages[-1]["content"]
    assert "Use key 'col' (NOT 'columnKey')" in second_messages[-1]["content"]
    assert "Response MUST include top-level keys: edits, explanation, confidence." in second_messages[-1]["content"]
    assert "Output ONLY valid JSON" in second_messages[-1]["content"]
    assert "Previous invalid output (truncated): not-json" in second_messages[-1]["content"]


def test_prompt_contains_literal_heuristics() -> None:
    assert prompt_analysis.prompt_contains_literal("first name: Holden")
    assert prompt_analysis.prompt_contains_literal('name "Holden"')
    assert prompt_analysis.prompt_contains_literal("school year 2024")
    assert prompt_analysis.prompt_contains_literal("grade 11")
    assert prompt_analysis.prompt_contains_literal("active true")
    assert prompt_analysis.prompt_contains_literal("student name Holden")
    assert not prompt_analysis.prompt_contains_literal("show student enrollment by race")


def test_expand_geo_literal() -> None:
    assert edit_inspector._expand_geo_literal("Mexico") == ["Mexico", "MX"]
    assert edit_inspector._expand_geo_literal("CA") == ["CA", "California"]
    assert edit_inspector._expand_geo_literal("California") == ["California", "CA"]
    assert edit_inspector._expand_geo_literal("unknown") == ["unknown"]


def test_expand_ordinal_literal() -> None:
    assert edit_inspector._expand_ordinal_literal("3rd") == ["3rd", "third"]
    assert edit_inspector._expand_ordinal_literal("third") == ["third", "3rd"]
    assert edit_inspector._expand_ordinal_literal("4th") == ["4th", "fourth"]
    assert edit_inspector._expand_ordinal_literal("fourth") == ["fourth", "4th"]
    assert edit_inspector._expand_ordinal_literal("11th") == ["11th", "eleventh"]
    assert edit_inspector._expand_ordinal_literal("grade") == ["grade"]


def test_to_grade_integer() -> None:
    assert edit_inspector._to_grade_integer("3rd") == 3
    assert edit_inspector._to_grade_integer("third") == 3
    assert edit_inspector._to_grade_integer("grade 4") == 4
    assert edit_inspector._to_grade_integer("11th grade") == 11
    assert edit_inspector._to_grade_integer("2") == 2
    assert edit_inspector._to_grade_integer(5) == 5
    assert edit_inspector._to_grade_integer("mexico") is None


def test_prompt_implies_aggregation_heuristics() -> None:
    assert prompt_analysis.prompt_implies_aggregation("How many students?")
    assert prompt_analysis.prompt_implies_aggregation("count students")
    assert prompt_analysis.prompt_implies_aggregation("total enrollment")
    assert prompt_analysis.prompt_implies_aggregation("average score")
    assert prompt_analysis.prompt_implies_aggregation("avg score")
    assert not prompt_analysis.prompt_implies_aggregation("show student records")


def test_prompt_requests_distinct_count_heuristics() -> None:
    assert prompt_analysis.prompt_requests_distinct_count("count distinct students")
    assert prompt_analysis.prompt_requests_distinct_count("how many unique students")
    assert not prompt_analysis.prompt_requests_distinct_count("how many students")


def test_prompt_implies_grouping_heuristics() -> None:
    assert prompt_analysis.prompt_implies_grouping("count students by race")
    assert prompt_analysis.prompt_implies_grouping("attendance per school")
    assert prompt_analysis.prompt_implies_grouping("distribution by gender")
    assert not prompt_analysis.prompt_implies_grouping("show students")


def test_prompt_implies_sorting_heuristics() -> None:
    assert prompt_analysis.prompt_implies_sorting("show top students")
    assert prompt_analysis.prompt_implies_sorting("courses sorted by credits descending")
    assert prompt_analysis.prompt_implies_sorting("rank schools by performance")
    assert not prompt_analysis.prompt_implies_sorting("show students")


def test_prompt_implies_entity_listing_heuristics() -> None:
    assert prompt_analysis.prompt_implies_entity_listing("show students")
    assert prompt_analysis.prompt_implies_entity_listing("list all schools")
    assert prompt_analysis.prompt_implies_entity_listing("give me courses")
    assert not prompt_analysis.prompt_implies_entity_listing("count students by race")
    assert not prompt_analysis.prompt_implies_entity_listing("show attendance")


def test_edits_reference_columns_heuristic() -> None:
    assert edit_inspector.edits_reference_columns(
        [{"op": "addFilter"}, {"op": "setDomain"}]
    )
    assert not edit_inspector.edits_reference_columns(
        [{"op": "setDomain"}]
    )


def test_edits_have_aggregate_heuristic() -> None:
    assert edit_inspector.edits_have_aggregate(
        [{"op": "addAggregate"}, {"op": "addFilter"}]
    )
    assert not edit_inspector.edits_have_aggregate(
        [{"op": "addFilter"}]
    )


def test_edits_have_groupby_heuristic() -> None:
    assert edit_inspector.edits_have_groupby(
        [{"op": "addGroupBy"}, {"op": "addFilter"}]
    )
    assert not edit_inspector.edits_have_groupby(
        [{"op": "addFilter"}]
    )


def test_edits_have_sorting_heuristic() -> None:
    assert edit_inspector.edits_have_sorting(
        [{"op": "addSort"}, {"op": "addFilter"}]
    )
    assert not edit_inspector.edits_have_sorting(
        [{"op": "addFilter"}]
    )


def test_count_add_select_edits() -> None:
    assert edit_inspector.count_add_select_edits(
        [{"op": "addSelect"}, {"op": "addFilter"}, {"op": "addSelect"}]
    ) == 2


def test_has_identifier_projection() -> None:
    assert edit_inspector.has_identifier_projection(
        [{"op": "addSelect", "col": {"columnName": "first_name"}}]
    )
    assert edit_inspector.has_identifier_projection(
        [{"op": "addSelect", "col": {"columnName": "student_id"}}]
    )
    assert not edit_inspector.has_identifier_projection(
        [{"op": "addSelect", "col": {"columnName": "school_year"}}]
    )


def test_is_aggregation_only_heuristic() -> None:
    assert edit_inspector.is_aggregation_only(
        [{"op": "addAggregate"}, {"op": "addFilter"}]
    )
    assert not edit_inspector.is_aggregation_only(
        [{"op": "addAggregate"}, {"op": "addSelect"}]
    )
    assert not edit_inspector.is_aggregation_only(
        [{"op": "addFilter"}]
    )


def test_extract_column_refs_from_edits_dedupes() -> None:
    refs = edit_inspector.extract_column_refs_from_edits(
        [
            {"op": "addFilter", "col": {"modelColumnId": 10, "columnName": "first_name", "workspaceTableId": 24}},
            {"op": "addGroupBy", "col": {"modelColumnId": 10, "columnName": "first_name", "workspaceTableId": 24}},
            {"op": "addAggregate", "col": {"workspaceTableId": 24, "columnName": "last_name"}},
            {"op": "addFilter", "col": {"workspaceTableId": 24, "columnName": "last_name"}},
        ]
    )
    assert len(refs) == 2
    assert refs[0]["columnName"] == "first_name"
    assert refs[1]["columnName"] == "last_name"


def test_determine_default_aggregate_column_prefers_select_then_filter() -> None:
    from_select = edit_inspector.determine_default_aggregate_column(
        [
            {"op": "addSelect", "col": {"modelColumnId": 1, "columnName": "student_id", "workspaceTableId": 24}},
            {"op": "addFilter", "col": {"modelColumnId": 2, "columnName": "first_name", "workspaceTableId": 24}},
        ]
    )
    assert from_select is not None
    assert from_select["columnName"] == "student_id"

    from_filter = edit_inspector.determine_default_aggregate_column(
        [
            {"op": "addFilter", "col": {"modelColumnId": 2, "columnName": "first_name", "workspaceTableId": 24}},
        ]
    )
    assert from_filter is not None
    assert from_filter["columnName"] == "first_name"

    assert edit_inspector.determine_default_aggregate_column([{"op": "setDomain", "domainId": 1}]) is None


def test_determine_default_groupby_columns_prefers_filter_select_for_aggregate_case() -> None:
    cols = edit_inspector.determine_default_groupby_columns(
        [
            {"op": "addAggregate", "col": {"modelColumnId": 2, "columnName": "student_id", "workspaceTableId": 24}},
            {"op": "addFilter", "col": {"modelColumnId": 3, "columnName": "race", "workspaceTableId": 24}},
            {"op": "addSelect", "col": {"modelColumnId": 4, "columnName": "school", "workspaceTableId": 24}},
        ]
    )
    assert len(cols) == 2
    assert cols[0]["columnName"] == "race"
    assert cols[1]["columnName"] == "school"


def test_determine_default_groupby_columns_requires_single_column_outside_aggregate_case() -> None:
    assert edit_inspector.determine_default_groupby_columns(
        [{"op": "addFilter", "col": {"modelColumnId": 3, "columnName": "race", "workspaceTableId": 24}}]
    ) == [{"modelColumnId": 3, "columnName": "race", "workspaceTableId": 24}]
    assert edit_inspector.determine_default_groupby_columns(
        [
            {"op": "addFilter", "col": {"modelColumnId": 3, "columnName": "race", "workspaceTableId": 24}},
            {"op": "addSelect", "col": {"modelColumnId": 4, "columnName": "school", "workspaceTableId": 24}},
        ]
    ) == []


def test_determine_default_sort_heuristics() -> None:
    sort_edit = edit_inspector.determine_default_sort(
        [{"op": "addSelect", "col": {"modelColumnId": 1, "columnName": "credits", "workspaceTableId": 9}}],
        "show top courses",
    )
    assert sort_edit is not None
    assert sort_edit["dir"] == "desc"


def test_get_identifier_candidates_limits_to_two() -> None:
    candidates = [
        {"columnName": "school_year", "modelColumnId": 1, "workspaceTableId": 24},
        {"columnName": "first_name", "modelColumnId": 2, "workspaceTableId": 24},
        {"columnName": "student_id", "modelColumnId": 3, "workspaceTableId": 24},
        {"columnName": "last_name", "modelColumnId": 4, "workspaceTableId": 24},
    ]
    selected = edit_inspector.get_identifier_candidates(candidates)
    assert len(selected) == 2
    assert selected[0]["columnName"] == "student_id"
    assert selected[1]["columnName"] == "first_name"

    sort_edit = edit_inspector.determine_default_sort(
        [{"op": "addFilter", "col": {"modelColumnId": 2, "columnName": "credits", "workspaceTableId": 9}}],
        "show lowest courses",
    )
    assert sort_edit is not None
    assert sort_edit["dir"] == "asc"

    sort_edit = edit_inspector.determine_default_sort(
        [{"op": "addAggregate", "col": {"modelColumnId": 2, "columnName": "student_id", "workspaceTableId": 24}}],
        "count students",
    )
    assert sort_edit is not None
    assert sort_edit["dir"] == "desc"

def test_infer_domain_from_columns_single_result() -> None:
    class _SQL:
        def execute_query_mappings(self, query: str, params: Dict[str, Any]):
            _ = (query, params)
            return [{"domain_id": 6}]

    qf_inferred = domain_seeder.infer_domain_from_columns(
        workspace_id="ws-1",
        edits=[{"op": "addFilter", "col": {"workspaceTableId": 24}}],
        sql_executor=_SQL(),
    )
    assert qf_inferred == 6


def test_infer_domain_from_columns_ambiguous_returns_none() -> None:
    class _SQL:
        def execute_query_mappings(self, query: str, params: Dict[str, Any]):
            _ = (query, params)
            return [{"domain_id": 6}, {"domain_id": 7}]

    qf_inferred = domain_seeder.infer_domain_from_columns(
        workspace_id="ws-1",
        edits=[{"op": "addSelect", "col": {"workspaceTableId": 24}}],
        sql_executor=_SQL(),
    )
    assert qf_inferred is None


def test_suggest_retries_when_literals_present_but_filters_missing(client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"addSelect","col":{"modelColumnId":351,"columnName":"first_name","workspaceTableId":24},"alias":"first_name"}],'
                                '"explanation":"selected first name","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"addSelect","col":{"modelColumnId":351,"columnName":"first_name","workspaceTableId":24},"alias":"first_name"},'
                                '{"op":"addFilter","col":{"modelColumnId":351,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"}],'
                                '"explanation":"added literal filter","confidence":0.85}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    body = _request_body()
    body["prompt"] = "Find first name: Holden"
    response = client.post(
        "/api/ai/suggest",
        json=body,
        headers=_headers("ws-1"),
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert len(calls) == 2
    assert any(edit["op"] == "addFilter" for edit in data["edits"])
    assert (
        "You failed to generate required addFilter edits. Every literal constraint must produce an addFilter. Regenerate."
        in calls[1]["json"]["messages"][-1]["content"]
    )


def test_suggest_returns_first_valid_response_if_filter_retry_output_is_invalid(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"addSelect","col":{"modelColumnId":351,"columnName":"first_name","workspaceTableId":24},"alias":"first_name"}],'
                                '"explanation":"first pass","confidence":0.7}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse({"choices": [{"message": {"content": "not-json"}}]}),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    body = _request_body()
    body["prompt"] = "Find first name: Holden"
    response = client.post(
        "/api/ai/suggest",
        json=body,
        headers=_headers("ws-1"),
    )

    assert response.status_code == 200
    data = response.get_json()
    assert len(calls) == 2
    assert data["debug"]["attempts"] == 2
    assert data["explanation"] == "first pass"
    assert all(edit["op"] != "addFilter" for edit in data["edits"])


def test_suggest_retries_when_setdomain_missing_and_inference_is_ambiguous(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    payload = _request_body()
    payload["domainContext"]["selectedDomainId"] = None
    payload["domainContext"]["domainCandidates"] = [
        {"domainId": 10, "name": "Students", "description": "Student records"},
        {"domainId": 11, "name": "Demographics", "description": "Demographic records"},
    ]
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":"school_year"}],'
                                '"explanation":"first pass","confidence":0.7}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":"school_year"}],'
                                '"explanation":"second pass","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)
    monkeypatch.setattr(domain_seeder, "infer_domain_from_columns", lambda **kwargs: None)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert _edit_by_op(data["edits"], "setDomain")["domainId"] == 10
    assert "You did not generate a required setDomain edit. Regenerate and include setDomain." in calls[1]["json"]["messages"][-1]["content"]


def test_suggest_retries_when_aggregate_missing_with_aggregation_intent(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    payload = _request_body()
    payload["prompt"] = "How many students have first name: Holden?"
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"}],'
                                '"explanation":"first pass","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"},'
                                '{"op":"addAggregate","func":"count_distinct","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
                                '"explanation":"second pass","confidence":0.9}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert _edit_by_op(data["edits"], "addAggregate")["func"] == "count"
    assert "You did not emit required addAggregate edit. Regenerate including addAggregate." in calls[1]["json"]["messages"][-1]["content"]


def test_suggest_aggregation_fallback_injects_addaggregate_on_attempt_two(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    payload = _request_body()
    payload["prompt"] = "How many students have first name: Holden?"
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"}],'
                                '"explanation":"first pass","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"}],'
                                '"explanation":"second pass still missing aggregate","confidence":0.7}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert _edit_by_op(data["edits"], "addAggregate")["func"] == "count"
    assert _edit_by_op(data["edits"], "addAggregate")["alias"] == "count_result"
    assert isinstance(data["sqlJson"]["aggs"], dict)


def test_suggest_keeps_count_distinct_when_prompt_requests_unique(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _request_body()
    payload["prompt"] = "How many unique students have first name: Holden?"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"},'
        '{"op":"addAggregate","func":"count_distinct","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
        '"explanation":"ok","confidence":0.9}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert _edit_by_op(data["edits"], "addAggregate")["func"] == "count_distinct"


def test_suggest_retries_when_groupby_missing_with_grouping_intent(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    payload = _request_body()
    payload["prompt"] = "Count students by race"
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addFilter","col":{"modelColumnId":500,"columnName":"race","workspaceTableId":24},"operator":"equals","value":"Black"},'
                                '{"op":"addAggregate","func":"count","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
                                '"explanation":"first pass","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addFilter","col":{"modelColumnId":500,"columnName":"race","workspaceTableId":24},"operator":"equals","value":"Black"},'
                                '{"op":"addGroupBy","col":{"modelColumnId":500,"columnName":"race","workspaceTableId":24}},'
                                '{"op":"addAggregate","func":"count","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
                                '"explanation":"second pass","confidence":0.9}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert _edit_by_op(data["edits"], "addGroupBy")["col"]["columnName"] == "race"
    assert (
        "You did not emit required addGroupBy edit. Regenerate including addGroupBy for the grouping intent."
        in calls[1]["json"]["messages"][-1]["content"]
    )


def test_suggest_grouping_fallback_injects_groupby_on_attempt_two(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    payload = _request_body()
    payload["prompt"] = "Count students by race"
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addFilter","col":{"modelColumnId":500,"columnName":"race","workspaceTableId":24},"operator":"equals","value":"Black"},'
                                '{"op":"addAggregate","func":"count","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
                                '"explanation":"first pass","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addFilter","col":{"modelColumnId":500,"columnName":"race","workspaceTableId":24},"operator":"equals","value":"Black"},'
                                '{"op":"addAggregate","func":"count","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
                                '"explanation":"second pass still missing groupby","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert _edit_by_op(data["edits"], "addGroupBy")["col"]["columnName"] == "race"
    assert isinstance(data["sqlJson"]["aggs"], dict)
    assert len(data["sqlJson"]["aggs"]["groupBy"]) >= 1


def test_suggest_sorting_fallback_injects_addsort(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["prompt"] = "Show top courses"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addSelect","col":{"modelColumnId":700,"columnName":"available_credits","workspaceTableId":9},"alias":"available_credits"}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert _edit_by_op(data["edits"], "addSort")["dir"] == "desc"
    assert data["sqlJson"]["sorting"][0]["dir"] == "desc"


def test_suggest_aggregation_cleanup_removes_addselect_when_no_groupby(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _request_body()
    payload["prompt"] = "How many students have first name: Holden?"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addSelect","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"alias":"first_name"},'
        '{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"},'
        '{"op":"addAggregate","func":"count_distinct","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
        '"explanation":"ok","confidence":0.9}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert all(edit.get("op") != "addSelect" for edit in data["edits"])
    assert data["sqlJson"]["columns"] == []
    assert isinstance(data["sqlJson"]["aggs"], dict)


def test_suggest_sqljson_groupby_preserved_when_no_addaggregate(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["prompt"] = "Show students by year"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addGroupBy","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24}}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data["sqlJson"]["aggs"], dict)
    assert data["sqlJson"]["aggs"]["metrics"] == []
    assert len(data["sqlJson"]["aggs"]["groupBy"]) == 1


def test_suggest_seeds_domain_from_single_domain_candidate_when_selected_missing(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _request_body()
    payload["domainContext"]["selectedDomainId"] = None
    payload["domainContext"]["domainCandidates"] = [
        {"domainId": 44, "name": "Students", "description": "Student records"}
    ]
    payload["prompt"] = "Show students"
    content = (
        '{"edits":[{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":null}],'
        '"explanation":"selected year","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["sqlJson"]["domainId"] == 44


def test_projection_fallback_injects_addselect_for_filter_columns(client, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"}],'
        '"explanation":"ok","confidence":0.9}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert _edit_by_op(data["edits"], "addSelect")["col"]["columnName"] == "first_name"
    assert len(data["sqlJson"]["columns"]) >= 1


def test_projection_fallback_skips_aggregation_only_queries(client, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addFilter","col":{"modelColumnId":354,"columnName":"first_name","workspaceTableId":24},"operator":"equals","value":"Holden"},'
        '{"op":"addAggregate","func":"count","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_count"}],'
        '"explanation":"ok","confidence":0.9}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert all(edit.get("op") != "addSelect" for edit in data["edits"])
    assert data["sqlJson"]["columns"] == []


def test_suggest_retries_when_listing_intent_has_too_few_projection_columns(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    payload = _request_body()
    payload["prompt"] = "Show all students"
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":"school_year"}],'
                                '"explanation":"first pass","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":"school_year"},'
                                '{"op":"addSelect","col":{"modelColumnId":352,"columnName":"student_id","workspaceTableId":24},"alias":"student_id"}],'
                                '"explanation":"second pass","confidence":0.86}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert len(calls) == 2
    assert edit_inspector.count_add_select_edits(data["edits"]) >= 2
    assert (
        "You must include at least two projection columns when listing entities."
        in calls[1]["json"]["messages"][-1]["content"]
    )


def test_suggest_projection_completeness_fallback_injects_identifier_columns(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[Dict[str, Any]] = []
    payload = _request_body()
    payload["prompt"] = "Show students"
    responses = [
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":"school_year"}],'
                                '"explanation":"first pass","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"edits":[{"op":"setDomain","domainId":10},'
                                '{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":"school_year"}],'
                                '"explanation":"second pass still one projection","confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        ),
    ]

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["debug"]["attempts"] == 2
    assert len(calls) == 2
    select_cols = [
        edit["col"]["columnName"]
        for edit in data["edits"]
        if edit.get("op") == "addSelect" and isinstance(edit.get("col"), dict)
    ]
    assert "school_year" in select_cols
    assert "student_id" in select_cols
    assert len(data["sqlJson"]["columns"]) >= 2


def test_sqljson_projection_safety_net_populates_columns_from_filters(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["currentSqlJson"] = {
        "version": 1,
        "domainId": 10,
        "columns": [],
        "filters": {
            "type": "group",
            "id": "g1",
            "match": "and",
            "children": [
                {
                    "type": "condition",
                    "id": "c1",
                    "field": {
                        "modelColumnId": 354,
                        "columnName": "first_name",
                        "workspaceTableId": 24,
                        "exprId": None,
                        "alias": None,
                    },
                    "op": "equals",
                    "value": "Holden",
                }
            ],
        },
        "aggs": None,
        "sorting": [],
        "dataPrep": None,
        "distinct": False,
        "meta": {"prompt": "original"},
    }
    content = '{"edits":[],"explanation":"ok","confidence":0.8}'

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["sqlJson"]["columns"]) == 1
    assert data["sqlJson"]["columns"][0]["field"]["columnName"] == "first_name"


def test_suggest_does_not_override_existing_current_sqljson_domain(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["currentSqlJson"] = {"version": 1, "domainId": 99}
    payload["prompt"] = "Show students"
    content = (
        '{"edits":[{"op":"addSelect","col":{"modelColumnId":351,"columnName":"school_year","workspaceTableId":24},"alias":null}],'
        '"explanation":"selected year","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    assert data["sqlJson"]["domainId"] == 99


def test_suggest_returns_500_when_model_response_stays_invalid(client, monkeypatch: pytest.MonkeyPatch) -> None:
    invalid_schema = '{"edits":"wrong","explanation":"bad","confidence":2}'

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": invalid_schema}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=_request_body(), headers=_headers())
    assert response.status_code == 500
    data = response.get_json()
    assert data["error"] == "Invalid model response"
    assert data["details"]["type"] == "schema_validation_error"
    assert data["details"]["attempt"] == 2


def test_health_success(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AISuggestService, "health", lambda self: {"data": [{"id": "qwen25-7b"}]})

    response = client.get("/api/ai/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["model"] == "qwen25-7b"
    assert data["upstream"] == {"data": [{"id": "qwen25-7b"}]}


def test_health_unavailable_returns_503(client, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(self):
        raise vllm_client.requests.RequestException("connection refused")

    monkeypatch.setattr(AISuggestService, "health", _raise)

    response = client.get("/api/ai/health")
    assert response.status_code == 503
    data = response.get_json()
    assert data["status"] == "error"
    assert data["error"] == "vLLM unavailable"


def test_suggest_requires_workspace_header(client) -> None:
    with pytest.raises(ForgeError, match="Missing X-Workspace-Id header"):
        client.post(
            "/api/ai/suggest",
            json=_request_body(),
            headers={"Authorization": "Bearer test-token"},
        )


def test_suggest_calls_retrieval_when_candidates_missing(client, monkeypatch: pytest.MonkeyPatch) -> None:
    search_calls: List[Dict[str, Any]] = []

    class _SearchSvc:
        def search(self, **kwargs):
            search_calls.append(kwargs)
            return _retrieval_payload()

    monkeypatch.setattr(ai_routes, "EmbeddingSearchService", lambda: _SearchSvc())

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": '{"edits":[],"explanation":"ok","confidence":0.7}'}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post(
        "/api/ai/suggest",
        json={"mode": "ai_first", "prompt": "black students this year"},
        headers=_headers("ws-1"),
    )
    assert response.status_code == 200
    assert len(search_calls) == 1
    call = search_calls[0]
    assert call["query"] == "black students this year"
    assert call["workspace_id"] == "ws-1"
    assert call["domain_id"] is None
    assert call["kinds"] == ["domain", "column", "table"]
    assert call["limit"] == 20


def test_suggest_removes_unknown_grounding_edits(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class _SearchSvc:
        def search(self, **kwargs):
            _ = kwargs
            return _retrieval_payload()

    monkeypatch.setattr(ai_routes, "EmbeddingSearchService", lambda: _SearchSvc())

    model_content = (
        '{"edits":[{"op":"addSelect","col":{"modelColumnId":9999,"columnName":"unknown_col","workspaceTableId":24},"alias":null}],'
        '"explanation":"selected unknown column","confidence":0.9}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": model_content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post(
        "/api/ai/suggest",
        json={"mode": "ai_first", "prompt": "black students this year"},
        headers=_headers("ws-1"),
    )
    assert response.status_code == 200
    data = response.get_json()
    assert all(edit["op"] != "addSelect" for edit in data["edits"])
    assert data["confidence"] < 0.9
    assert "removed 1 edit(s)" in data["explanation"]
    assert data["sqlJson"]["version"] == 1


def test_suggest_passes_column_description_to_llm_prompt(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class _SearchSvc:
        def search(self, **kwargs):
            _ = kwargs
            return _retrieval_payload()

    monkeypatch.setattr(ai_routes, "EmbeddingSearchService", lambda: _SearchSvc())

    calls: List[Dict[str, Any]] = []

    def _fake_post(url: str, json: Dict[str, Any], timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse({"choices": [{"message": {"content": '{"edits":[],"explanation":"ok","confidence":0.8}'}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post(
        "/api/ai/suggest",
        json={"mode": "ai_first", "prompt": "black students this year"},
        headers=_headers("ws-1"),
    )
    assert response.status_code == 200
    prompt_content = calls[0]["json"]["messages"][1]["content"]
    assert '"description":"School year of enrollment"' in prompt_content


def test_suggest_expands_country_filter_to_include_abbreviation(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["prompt"] = "Show students in Mexico"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addFilter","col":{"modelColumnId":900,"columnName":"country","workspaceTableId":24},"operator":"equals","value":"Mexico"}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    filter_edit = _edit_by_op(data["edits"], "addFilter")
    assert filter_edit["operator"] == "in"
    assert filter_edit["value"] == ["Mexico", "MX"]
    condition = data["sqlJson"]["filters"]["children"][0]
    assert condition["op"] == "in"
    assert condition["value"] == ["Mexico", "MX"]


def test_suggest_expands_state_abbreviation_filter_to_include_name(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["prompt"] = "Show students in CA"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addFilter","col":{"modelColumnId":901,"columnName":"state","workspaceTableId":24},"operator":"equals","value":"CA"}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    filter_edit = _edit_by_op(data["edits"], "addFilter")
    assert filter_edit["operator"] == "in"
    assert filter_edit["value"] == ["CA", "California"]


def test_suggest_expands_ordinal_filter_to_include_word_variant(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["prompt"] = "Show students in 3rd grade"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addFilter","col":{"modelColumnId":902,"columnName":"grade_level","workspaceTableId":24},"operator":"equals","value":"3rd"}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    filter_edit = _edit_by_op(data["edits"], "addFilter")
    assert filter_edit["operator"] == "equals"
    assert filter_edit["value"] == 3


def test_suggest_non_grade_ordinal_still_expands_to_word_variant(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _request_body()
    payload["prompt"] = "Show students with rank 3rd"
    content = (
        '{"edits":[{"op":"setDomain","domainId":10},'
        '{"op":"addFilter","col":{"modelColumnId":903,"columnName":"rank","workspaceTableId":24},"operator":"equals","value":"3rd"}],'
        '"explanation":"ok","confidence":0.8}'
    )

    def _fake_post(_url: str, json: Dict[str, Any], timeout: int):
        _ = (json, timeout)
        return _FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(vllm_client.requests, "post", _fake_post)

    response = client.post("/api/ai/suggest", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.get_json()
    filter_edit = _edit_by_op(data["edits"], "addFilter")
    assert filter_edit["operator"] == "in"
    assert filter_edit["value"] == ["3rd", "third"]

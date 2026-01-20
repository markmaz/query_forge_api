from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions.service_error import ServiceError
from app.services.cohort_builder_vector_sql_json_service import CohortBuilderVectorSqlJsonService


def _sample_rows() -> list[dict]:
    return [
        {
            "columnName": "cohort_key",
            "workspaceTableId": 10,
            "modelColumnId": 1,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_patient",
            "dataType": "STRING",
            "nullable": True,
            "tableAlias": "patient",
            "isDefault": True,
        },
        {
            "columnName": "patient_gender",
            "workspaceTableId": 10,
            "modelColumnId": 2,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_patient",
            "dataType": "STRING",
            "nullable": True,
            "tableAlias": "patient",
            "isDefault": True,
        },
        {
            "columnName": "patient_birth_year",
            "workspaceTableId": 10,
            "modelColumnId": 3,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_patient",
            "dataType": "INT",
            "nullable": True,
            "tableAlias": "patient",
            "isDefault": True,
        },
        {
            "columnName": "state",
            "workspaceTableId": 10,
            "modelColumnId": 4,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_patient",
            "dataType": "STRING",
            "nullable": True,
            "tableAlias": "patient",
            "isDefault": True,
        },
        {
            "columnName": "year",
            "workspaceTableId": 11,
            "modelColumnId": 5,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_builder_diagnosis",
            "dataType": "INT",
            "nullable": True,
            "tableAlias": "dx",
        },
        {
            "columnName": "code",
            "workspaceTableId": 11,
            "modelColumnId": 6,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_builder_diagnosis",
            "dataType": "STRING",
            "nullable": True,
            "tableAlias": "dx",
        },
        {
            "columnName": "code",
            "workspaceTableId": 12,
            "modelColumnId": 7,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_builder_procedures",
            "dataType": "STRING",
            "nullable": True,
            "tableAlias": "px",
        },
        {
            "columnName": "year",
            "workspaceTableId": 12,
            "modelColumnId": 9,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_builder_procedures",
            "dataType": "INT",
            "nullable": True,
            "tableAlias": "px",
        },
        {
            "columnName": "code",
            "workspaceTableId": 13,
            "modelColumnId": 8,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_builder_drugs",
            "dataType": "STRING",
            "nullable": True,
            "tableAlias": "ndc",
        },
        {
            "columnName": "year",
            "workspaceTableId": 13,
            "modelColumnId": 10,
            "modelTableId": None,
            "modelTableName": None,
            "fullName": "analytics.workboard.cohort_builder_drugs",
            "dataType": "INT",
            "nullable": True,
            "tableAlias": "ndc",
        },
    ]


def _row(
    column_name: str | None,
    *,
    table_alias: str = "patient",
    workspace_table_id: int = 1,
    model_column_id: int = 1,
    is_default: bool = True,
) -> dict:
    return {
        "columnName": column_name,
        "workspaceTableId": workspace_table_id,
        "modelColumnId": model_column_id,
        "modelTableId": None,
        "modelTableName": None,
        "fullName": "analytics.workboard.table",
        "dataType": "STRING",
        "nullable": True,
        "tableAlias": table_alias,
        "isDefault": is_default,
    }


def test_build_sql_json_happy_path(monkeypatch) -> None:
    rows = _sample_rows()

    def fake_get_domain(self, *, workspace_id: str, domain_name: str) -> dict:
        assert workspace_id == "ws1"
        assert domain_name == "Cohort Builder"
        return {"domain_id": 123}

    def fake_list_available_columns(self, query) -> dict:
        assert query.workspace_id == "ws1"
        assert query.user_id == "user1"
        assert query.domain_id == 123
        return {"rows": rows}

    class FixedDatetime:
        @classmethod
        def utcnow(cls) -> datetime:
            return datetime(2024, 1, 1)

    monkeypatch.setattr(
        "app.services.cohort_builder_vector_sql_json_service.DomainTableReadService.get_domain",
        fake_get_domain,
    )
    monkeypatch.setattr(
        "app.services.cohort_builder_vector_sql_json_service.BuilderColumnFeedService.list_available_columns",
        fake_list_available_columns,
    )
    monkeypatch.setattr(
        "app.services.cohort_builder_vector_sql_json_service.datetime",
        FixedDatetime,
    )

    svc = CohortBuilderVectorSqlJsonService()
    sql_json = svc.build(
        workspace_id="ws1",
        user_id="user1",
        demographics={
            "age": {"lower_bound": 30, "upper_bound": 40},
            "gender": ["Female", "F"],
            "location": ["CA", "CA", "NY"],
            "dx_year": {"lower_bound": 2022, "upper_bound": 2024},
        },
        conditions={"c1": {"code": "E11", "logic": "OR"}},
        procedures={"p1": {"code": "43846", "logic": "OR"}},
        drugs={"d1": {"code": "00169477211", "logic": "OR"}},
    )

    assert sql_json["domainId"] == 123
    assert sql_json["distinct"] is True
    assert sql_json["filters"]["id"] == "root"

    alias_map = {c["alias"]: c["columnName"] for c in sql_json["columns"] if c.get("alias")}
    assert alias_map == {
        "dx_code": "code",
        "dx_year": "year",
        "px_code": "code",
        "px_year": "year",
        "ndc_code": "code",
        "ndc_year": "year",
    }

    groups = {g["id"] for g in sql_json["filters"]["children"]}
    assert {"demographics", "dx_year", "conditions", "procedures", "drugs"} <= groups


def test_build_missing_domain_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.cohort_builder_vector_sql_json_service.DomainTableReadService.get_domain",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "app.services.cohort_builder_vector_sql_json_service.BuilderColumnFeedService.list_available_columns",
        lambda *_args, **_kwargs: {"rows": []},
    )
    svc = CohortBuilderVectorSqlJsonService()
    with pytest.raises(ServiceError, match="Cohort Builder domain not found"):
        svc.build(workspace_id="ws1", user_id="user1")


def test_extract_codes_mixed_logic_warns() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    warnings: list[str] = []
    codes, match = svc._extract_codes(
        {
            "a": {"code": "A1", "logic": "AND", "negation": True},
            "b": {"code": "B2", "logic": "OR"},
        },
        warnings,
        label="conditions",
    )
    assert codes == ["A1", "B2"]
    assert match == "and"
    assert "Mixed logic for conditions; defaulting to AND." in warnings
    assert "Negation not supported for conditions; ignoring negation." in warnings


def test_build_column_map_prefers_default_and_skips_missing_name() -> None:
    rows = [
        _row(None),
        _row("a", is_default=False),
        _row("a", is_default=True, model_column_id=2),
        _row("b", is_default=False, model_column_id=3),
    ]
    svc = CohortBuilderVectorSqlJsonService()

    col_map = svc._build_column_map(rows)

    assert col_map["a"]["modelColumnId"] == 2
    assert col_map["b"]["modelColumnId"] == 3


def test_aliases_used_by_filters_handles_groups_and_non_dict() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    filters = {
        "type": "group",
        "children": [
            {"type": "condition", "field": {"tableAlias": "Dx"}},
            {"type": "condition", "field": "bad"},
            "not-a-dict",
        ],
    }

    used = svc._aliases_used_by_filters(filters)

    assert used == {"dx"}


def test_build_projection_skips_unselected_aliases_and_warns_missing() -> None:
    rows = [
        _row(None),
        _row("cohort_key", model_column_id=1),
        _row("patient_birth_year", model_column_id=2),
        _row("state", model_column_id=3),
        _row("code", table_alias="dx", workspace_table_id=11, model_column_id=4),
    ]
    warnings: list[str] = []
    filters = {
        "type": "group",
        "children": [
            {"type": "condition", "field": {"tableAlias": "dx"}},
            {"type": "condition", "field": {"tableAlias": "ndc"}},
        ],
    }
    svc = CohortBuilderVectorSqlJsonService()

    out = svc._build_projection(rows, warnings, filters=filters)

    aliases = [c.get("alias") for c in out if c.get("alias")]
    assert "dx_code" in aliases
    assert "dx_year" not in aliases
    assert "Missing column: dx.year" in warnings
    assert "Missing column: ndc.code" in warnings
    assert "Missing column: ndc.year" in warnings


def test_col_key_helpers_add_warnings() -> None:
    rows = [_row("code", table_alias="px")]
    col_map = {"code": rows[0]}
    warnings: list[str] = []
    svc = CohortBuilderVectorSqlJsonService()

    assert svc._col_key(col_map, "missing", warnings) is None
    assert "Missing domain column: missing" in warnings

    assert svc._col_key_for_alias(rows, "code", "dx", warnings) is None
    assert "Missing domain column: dx.code" in warnings


def test_build_demographics_group_empty_returns_none() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    warnings: list[str] = []

    assert svc._build_demographics_group({}, [], {}, warnings) is None


def test_build_demographics_group_normalizes_gender_and_state() -> None:
    rows = [
        _row("patient_birth_year", model_column_id=1),
        _row("patient_gender", model_column_id=2),
        _row("state", table_alias="other", model_column_id=3),
    ]
    col_map = {r["columnName"]: r for r in rows if r.get("columnName")}
    warnings: list[str] = []
    svc = CohortBuilderVectorSqlJsonService()

    group = svc._build_demographics_group(
        {
            "age": {"lower": 30, "upper": 40},
            "gender": ["", "Male", "Female", "X"],
            "state": "CA, NY",
        },
        rows,
        col_map,
        warnings,
    )

    assert group is not None
    cond_ids = {c["id"] for c in group["children"]}
    assert {"demo_age", "demo_gender", "demo_state"} <= cond_ids


def test_build_demographics_group_gender_string() -> None:
    rows = [
        _row("patient_gender", model_column_id=1),
    ]
    col_map = {r["columnName"]: r for r in rows if r.get("columnName")}
    warnings: list[str] = []
    svc = CohortBuilderVectorSqlJsonService()

    group = svc._build_demographics_group(
        {"gender": "Male, Female"},
        rows,
        col_map,
        warnings,
    )

    assert group is not None


def test_build_dx_year_group_returns_none_for_missing_parts() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    warnings: list[str] = []
    rows = [_row("year", table_alias="other")]
    col_map = {r["columnName"]: r for r in rows if r.get("columnName")}

    assert svc._build_dx_year_group({}, rows, col_map, warnings) is None
    assert (
        svc._build_dx_year_group(
            {"dx_year": {"lower": 2020, "upper": 2021}},
            rows,
            col_map,
            warnings,
        )
        is None
    )


def test_build_conditions_group_empty_and_missing_field() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    warnings: list[str] = []
    rows: list[dict] = []
    col_map: dict[str, dict] = {}

    assert svc._build_conditions_group({}, rows, col_map, warnings) is None
    assert (
        svc._build_conditions_group({"a": {"code": "E11", "logic": "AND"}}, rows, col_map, warnings)
        is None
    )


def test_build_procedures_group_empty_and_missing_field() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    warnings: list[str] = []
    rows: list[dict] = []
    col_map: dict[str, dict] = {}

    assert svc._build_procedures_group({}, rows, col_map, warnings) is None
    assert (
        svc._build_procedures_group({"a": {"code": "43846", "logic": "OR"}}, rows, col_map, warnings)
        is None
    )


def test_build_drugs_group_caps_and_missing_field() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    warnings: list[str] = []

    assert svc._build_drugs_group({}, [], {}, warnings) is None
    assert (
        svc._build_drugs_group({"a": {"code": "A1", "logic": "OR"}}, [], {}, warnings)
        is None
    )

    codes = [f"c{i}" for i in range(600)]
    payload = {"a": {"code": ",".join(codes), "logic": "OR"}}
    rows = [_row("code", table_alias="ndc", workspace_table_id=2)]
    col_map = {r["columnName"]: r for r in rows if r.get("columnName")}
    warnings = []

    group = svc._build_drugs_group(payload, rows, col_map, warnings)

    assert group is not None
    assert "Drug NDC list capped at 500 codes." in warnings
    inner = group["children"][0]["children"]
    assert len(inner) == 500


def test_parse_bounds_variants() -> None:
    svc = CohortBuilderVectorSqlJsonService()

    assert svc._parse_bounds({"age": {"lower_bound": "1", "upper_bound": "2"}}, "age") == (1, 2)
    assert svc._parse_bounds({"age": "x", "age_lower": "3", "age_upper": "4"}, "age") == (3, 4)
    assert svc._parse_bounds({}, "age") is None
    assert svc._parse_bounds({"age": {"lower": "x", "upper": "y"}}, "age") is None


def test_extract_codes_or_logic_and_skip_non_dict() -> None:
    svc = CohortBuilderVectorSqlJsonService()
    warnings: list[str] = []

    codes, match = svc._extract_codes(
        {"a": {"code": "A1", "logic": "OR"}, "b": "skip"},
        warnings,
        label="drugs",
    )

    assert codes == ["A1"]
    assert match == "or"

from __future__ import annotations

from app.models.ai_suggest import (
    AddAggregateEdit,
    AddFilterEdit,
    AddGroupByEdit,
    AddSelectEdit,
    AddSortEdit,
    SetDomainEdit,
    SqlColumnKey,
)
from app.services.sqljson_apply_service import apply_edits


def _col(model_column_id: int, column_name: str, workspace_table_id: int = 24) -> SqlColumnKey:
    return SqlColumnKey(
        modelColumnId=model_column_id,
        columnName=column_name,
        workspaceTableId=workspace_table_id,
    )


def test_apply_edits_builds_sqlqueryjsonv1_from_sequence() -> None:
    edits = [
        SetDomainEdit(op="setDomain", domainId=10),
        AddSelectEdit(op="addSelect", col=_col(351, "school_year"), alias="school_year"),
    ]
    sqljson = apply_edits(None, edits, prompt="student trend")

    assert sqljson["version"] == 1
    assert sqljson["domainId"] == 10
    assert len(sqljson["columns"]) == 1
    assert sqljson["columns"][0]["field"]["columnName"] == "school_year"
    assert sqljson["columns"][0]["alias"] == "school_year"
    assert sqljson["meta"]["prompt"] == "student trend"


def test_apply_edits_add_filter_creates_root_group_and_condition() -> None:
    edits = [
        AddFilterEdit(
            op="addFilter",
            col=_col(777, "race_ethnicity"),
            operator="equals",
            value="Black",
        )
    ]
    sqljson = apply_edits(None, edits, prompt="black students")

    assert sqljson["filters"]["type"] == "group"
    assert sqljson["filters"]["match"] == "and"
    assert len(sqljson["filters"]["children"]) == 1
    condition = sqljson["filters"]["children"][0]
    assert condition["type"] == "condition"
    assert condition["field"]["columnName"] == "race_ethnicity"
    assert condition["op"] == "equals"
    assert condition["value"] == "Black"


def test_apply_edits_add_aggregate_creates_aggs_enabled_metrics_and_groupby() -> None:
    edits = [
        AddGroupByEdit(op="addGroupBy", col=_col(351, "school_year")),
        AddAggregateEdit(op="addAggregate", func="count", col=_col(352, "student_id"), alias="student_count"),
    ]
    sqljson = apply_edits(None, edits, prompt="count students")

    assert sqljson["aggs"]["enabled"] is True
    assert len(sqljson["aggs"]["groupBy"]) == 1
    assert sqljson["aggs"]["groupBy"][0]["columnName"] == "school_year"
    assert len(sqljson["aggs"]["metrics"]) == 1
    metric = sqljson["aggs"]["metrics"][0]
    assert metric["fn"] == "count"
    assert metric["field"]["columnName"] == "student_id"
    assert metric["label"] == "student_count"


def test_apply_edits_add_filter_supports_extended_operators() -> None:
    edits = [
        AddFilterEdit(op="addFilter", col=_col(1, "name"), operator="not_equals", value="Alice"),
        AddFilterEdit(op="addFilter", col=_col(2, "state"), operator="not_in", value=["CA", "NY"]),
        AddFilterEdit(op="addFilter", col=_col(3, "middle_name"), operator="is_null", value=None),
        AddFilterEdit(op="addFilter", col=_col(4, "nickname"), operator="is_not_null", value=None),
        AddFilterEdit(op="addFilter", col=_col(5, "score"), operator="gte", value=80),
        AddFilterEdit(op="addFilter", col=_col(6, "score"), operator="lte", value=100),
    ]
    sqljson = apply_edits(None, edits, prompt="extended operators")

    children = ((sqljson.get("filters") or {}).get("children") or [])
    assert [item.get("op") for item in children] == [
        "not_equals",
        "not_in",
        "is_null",
        "is_not_null",
        "gte",
        "lte",
    ]


def test_apply_edits_add_sort_appends_sorting_and_dedupes() -> None:
    edits = [
        AddSortEdit(op="addSort", col=_col(351, "school_year"), dir="asc"),
        AddSortEdit(op="addSort", col=_col(351, "school_year"), dir="asc"),
        AddSortEdit(op="addSort", col=_col(352, "student_id"), dir="desc"),
    ]
    sqljson = apply_edits(None, edits, prompt="sort students")

    assert len(sqljson["sorting"]) == 2
    assert sqljson["sorting"][0]["col"]["columnName"] == "school_year"
    assert sqljson["sorting"][0]["dir"] == "asc"
    assert sqljson["sorting"][1]["col"]["columnName"] == "student_id"
    assert sqljson["sorting"][1]["dir"] == "desc"

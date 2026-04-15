from __future__ import annotations

import pytest

from app.services.execution.execution_result_formatter import (
    build_assistant_result_message,
    columns_from_manifest,
    exec_rows_to_dicts,
    extract_total,
)


def test_columns_from_manifest_shapes_columns() -> None:
    out = columns_from_manifest(
        {
            "schema": {
                "columns": [
                    {"name": "school_name", "type": "STRING", "nullable": True},
                    {"name": "students"},
                ]
            }
        }
    )

    assert out == [
        {"key": "school_name", "label": "school_name", "dataType": "STRING", "nullable": True},
        {"key": "students", "label": "students"},
    ]


def test_exec_rows_to_dicts_maps_tuple_rows() -> None:
    out = exec_rows_to_dicts(
        [[1, "alpha"], [2, "beta"]],
        [{"key": "id"}, {"key": "name"}],
    )

    assert out == [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]


def test_extract_total_reads_total_column() -> None:
    assert extract_total([{"total": "7"}]) == 7


def test_build_assistant_result_message_renders_markdown() -> None:
    msg = build_assistant_result_message(
        rows=[{"school_name": "Barksdale Elementary", "students": 120}],
        columns=[{"key": "school_name"}, {"key": "students"}],
        total=1,
        limit=200,
        offset=0,
    )

    assert msg["role"] == "assistant"
    assert msg["kind"] == "execution_result"
    assert msg["format"] == "markdown"
    content = str(msg["content"])
    assert "Query complete." in content
    assert "| school_name | students |" in content


def test_build_assistant_result_message_ignores_invalid_total_values() -> None:
    msg = build_assistant_result_message(
        rows=[],
        columns=[],
        total="not-a-number",
        limit=None,
        offset=None,
    )

    assert "(total" not in str(msg["content"])


def test_build_assistant_result_message_surfaces_unexpected_total_errors() -> None:
    class _BrokenTotal:
        def __int__(self) -> int:
            raise AssertionError("unexpected total coercion failure")

    with pytest.raises(AssertionError, match="unexpected total coercion failure"):
        build_assistant_result_message(
            rows=[],
            columns=[],
            total=_BrokenTotal(),
            limit=None,
            offset=None,
        )

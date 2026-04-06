from __future__ import annotations

import pytest

import app.services.domain_resolution.plan_builder as plan_builder
from app.exceptions.forge_error import ForgeError
from app.services.domain_resolution.plan_builder import build_plan_tables, normalize_policy, to_plan_join


def test_build_plan_tables_assigns_aliases_and_normalizes_values():
    tables, alias_map = build_plan_tables(
        [
            {
                "workspace_table_id": 10,
                "table_alias": "pt",
                "is_primary": 1,
                "sort_order": 0,
                "filter_mode": "AUTO",
                "cardinality": "ONE",
                "full_name": "main.asset.patients",
            },
            {
                "workspace_table_id": 11,
                "table_alias": None,
                "is_primary": 0,
                "sort_order": 1,
                "filter_mode": "WHERE",
                "cardinality": "MANY",
                "full_name": "main.asset.codes",
            },
        ]
    )

    assert alias_map == {10: "pt", 11: "t0"}
    assert tables[1].filter_mode == "WHERE"
    assert tables[1].cardinality == "MANY"


def test_build_plan_tables_rejects_invalid_filter_mode():
    with pytest.raises(ForgeError, match="Invalid filter_mode"):
        build_plan_tables(
            [
                {
                    "workspace_table_id": 10,
                    "table_alias": "pt",
                    "is_primary": 1,
                    "sort_order": 0,
                    "filter_mode": "BAD",
                    "cardinality": "ONE",
                    "full_name": "main.asset.patients",
                }
            ]
        )


def test_normalize_policy_rejects_unknown_value():
    with pytest.raises(ForgeError, match="Invalid column_name_policy"):
        normalize_policy("bad")


def test_to_plan_join_parses_json_spec():
    join = to_plan_join(
        {
            "id": 1,
            "from_workspace_table_id": 10,
            "to_workspace_table_id": 11,
            "join_type": "left",
            "join_spec_json": '{"on": []}',
            "sort_order": 0,
        }
    )

    assert join.join_id == "1"
    assert join.join_type == "LEFT"
    assert join.join_spec == {"on": []}


def test_to_plan_join_surfaces_unexpected_json_parser_errors(monkeypatch: pytest.MonkeyPatch):
    def _boom(_value):
        raise AssertionError("unexpected join spec parser bug")

    monkeypatch.setattr(plan_builder.json, "loads", _boom)

    with pytest.raises(AssertionError, match="unexpected join spec parser bug"):
        to_plan_join(
            {
                "id": 1,
                "from_workspace_table_id": 10,
                "to_workspace_table_id": 11,
                "join_type": "left",
                "join_spec_json": '{"on": []}',
                "sort_order": 0,
            }
        )

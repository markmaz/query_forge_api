from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolution.join_path_service import DomainJoinPathService
from app.services.domain_resolution.models import DomainPlan, DomainPlanJoin, DomainPlanTable


def _plan() -> DomainPlan:
    return DomainPlan(
        primary=DomainPlanTable(
            workspace_table_id=1,
            full_name="main.asset.patients",
            alias="t0",
            table_alias="pt",
            is_primary=True,
            sort_order=0,
            filter_mode="AUTO",
            cardinality="ONE",
        ),
        tables=[],
        joins=[
            DomainPlanJoin(
                join_id="1",
                from_workspace_table_id=1,
                to_workspace_table_id=2,
                join_type="INNER",
                join_spec={"on": []},
                sort_order=0,
            ),
            DomainPlanJoin(
                join_id="2",
                from_workspace_table_id=2,
                to_workspace_table_id=3,
                join_type="LEFT",
                join_spec={"on": []},
                sort_order=1,
            ),
        ],
        alias_by_workspace_table_id={},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )


def test_get_join_path_finds_route():
    service = DomainJoinPathService()
    path = service.get_join_path(_plan(), 3)
    assert [p.join_id for p in path] == ["1", "2"]


def test_get_join_path_raises_when_missing():
    service = DomainJoinPathService()
    with pytest.raises(ForgeError, match="Join path not found"):
        service.get_join_path(_plan(), 99)


def test_reverse_join_swaps_join_spec():
    service = DomainJoinPathService()
    join = DomainPlanJoin(
        join_id="1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec={
            "on": [
                {
                    "op": "=",
                    "left": {"workspaceTableId": 1, "columnName": "k_student"},
                    "right": {"workspaceTableId": 2, "columnName": "k_student"},
                }
            ]
        },
        sort_order=0,
    )
    reversed_join = service.reverse_join(join)
    assert reversed_join.join_id == "1:rev"
    assert reversed_join.join_spec["on"][0]["left"]["workspaceTableId"] == 2
    assert reversed_join.join_spec["on"][0]["right"]["workspaceTableId"] == 1

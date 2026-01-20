from __future__ import annotations

import pytest

from app.models.cluster_size_enum import ClusterSize
from app.models.warehouse import Warehouse
from app.models.warehouse_type_enum import WarehouseType


def test_warehouse_setters_validate_types() -> None:
    wh = Warehouse()

    with pytest.raises(ValueError):
        wh.warehouse_id = 123
    with pytest.raises(ValueError):
        wh.name = 123
    with pytest.raises(ValueError):
        wh.cluster_size = "small"
    with pytest.raises(ValueError):
        wh.auto_stop_minutes = "abc"
    with pytest.raises(ValueError):
        wh.min_number_clusters = "1"
    with pytest.raises(ValueError):
        wh.max_number_clusters = "1"
    with pytest.raises(ValueError):
        wh.creator_name = 123
    with pytest.raises(ValueError):
        wh.enable_serverless_compute = "true"
    with pytest.raises(ValueError):
        wh.server_type = 123
    with pytest.raises(ValueError):
        wh.jdbc_url = 123
    with pytest.raises(ValueError):
        wh.odbc_params = "bad"

    wh.warehouse_id = "wh1"
    wh.name = "Warehouse"
    wh.cluster_size = ClusterSize.S
    wh.auto_stop_minutes = "30"
    wh.min_number_clusters = 1
    wh.max_number_clusters = 2
    wh.creator_name = "Creator"
    wh.enable_serverless_compute = True
    wh.server_type = WarehouseType.PRO.value
    wh.jdbc_url = "jdbc://example"
    wh.odbc_params = {"path": "x"}


def test_warehouse_to_dict_and_create() -> None:
    wh = Warehouse(cluster_size=ClusterSize.M)
    data = wh.to_dict()
    assert data["cluster_size"] == ClusterSize.M.value

    payload = wh.to_create()
    assert payload["enable_serverless_compute"] in {"True", "False"}


def test_warehouse_from_dict_defaults() -> None:
    wh = Warehouse.from_dict(
        {
            "cluster_size": "BAD",
            "warehouse_type": "BAD",
        }
    )
    assert wh.cluster_size == ClusterSize.XXS
    assert wh.server_type == WarehouseType.PRO.value

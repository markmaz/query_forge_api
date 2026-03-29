from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# We patch the SQLAlchemy engine at module level so no real DB is needed.
# The service uses: engine.connect() -> conn.execute(text(sql), params) -> .mappings().all()

def _make_conn(rows):
    """Return a mock context-manager connection that yields rows on execute.

    result.mappings().all() returns `rows` (for SELECT queries).
    result.fetchone() returns a 1-tuple `(len(rows),)` (for COUNT queries: `fetchone()[0]` == int).
    result.rowcount == len(rows) (for UPDATE/DELETE queries: 0 means not found).
    """
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    result.fetchone.return_value = (len(rows),)
    result.rowcount = len(rows)
    conn = MagicMock()
    conn.execute.return_value = result
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    return conn, cm


@pytest.fixture()
def svc():
    from app.services.dictionary.dictionary_service import DictionaryService
    return DictionaryService()


def test_list_tables_returns_rows(svc):
    raw = [
        {"id": 1, "table_name": "dim_prov", "full_name": "asset.dim_prov",
         "schema_name": "asset", "catalog_name": None, "description": None},
    ]
    conn, cm = _make_conn(raw)
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.list_tables(workspace_id="ws-1", q=None, limit=500, offset=0)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["table_name"] == "dim_prov"
    assert result["total"] == 1
    assert result["limit"] == 500
    assert result["offset"] == 0


def test_list_tables_applies_q_filter(svc):
    """When q is provided the call must include it; we verify the conn.execute args."""
    conn, cm = _make_conn([])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        svc.list_tables(workspace_id="ws-1", q="prov", limit=10, offset=0)
    call_args = conn.execute.call_args
    # params dict must include the q value as a LIKE pattern
    params = call_args[0][1]
    assert "%" in params.get("q", "")


def test_list_columns_returns_full_shape(svc):
    raw = [{
        "id": 5, "workspace_table_id": 1, "column_name": "npi",
        "data_type": "string", "ordinal_position": 1,
        "description": "10-digit NPI", "is_active": 1,
        "semantic_type": None, "semantic_entity": None,
        "semantic_sub_type": None, "semantic_confidence": None,
        "sample_values_json": '["val1","val2"]',
        "sample_stats_json": '{"min":0}',
        "sample_ran_at": None, "sample_error": None,
        "table_name": "dim_prov", "full_name": "asset.dim_prov",
    }]
    conn, cm = _make_conn(raw)
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.list_columns(
            workspace_id="ws-1", workspace_table_id=1, q=None, active_only=True
        )
    col = result["rows"][0]
    # JSON fields must be pre-parsed
    assert col["sample_values_json"] == ["val1", "val2"]
    assert col["sample_stats_json"] == {"min": 0}
    # is_active coerced to bool
    assert col["is_active"] is True
    assert col["table_name"] == "dim_prov"


def test_list_columns_serializes_decimal_fields(svc):
    raw = [{
        "id": 5, "workspace_table_id": 1, "column_name": "npi",
        "data_type": "string", "ordinal_position": 1,
        "description": "10-digit NPI", "is_active": 1,
        "semantic_type": None, "semantic_entity": None,
        "semantic_sub_type": None, "semantic_confidence": Decimal("0.92"),
        "sample_values_json": ["val1", "val2"],
        "sample_stats_json": {"null_pct": Decimal("0.0"), "approx_distinct": Decimal("2")},
        "sample_ran_at": None, "sample_error": None,
        "table_name": "dim_prov", "full_name": "asset.dim_prov",
    }]
    conn, cm = _make_conn(raw)
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.list_columns(
            workspace_id="ws-1", workspace_table_id=1, q=None, active_only=True
        )
    col = result["rows"][0]
    assert col["semantic_confidence"] == 0.92
    assert col["sample_stats_json"] == {"null_pct": 0.0, "approx_distinct": 2.0}


def test_list_columns_404_when_table_not_in_workspace(svc):
    """Table 999 does not belong to this workspace — should raise 404."""
    # The service makes two engine.connect() calls:
    #   1. Main column query → empty (no columns found)
    #   2. Existence check → fetchone() must return None (table not in workspace)
    # _make_conn([]) returns fetchone() = (0,) which is truthy; create cm_check manually.
    conn_main, cm_main = _make_conn([])
    conn_check = MagicMock()
    conn_check.execute.return_value.fetchone.return_value = None
    cm_check = MagicMock()
    cm_check.__enter__ = MagicMock(return_value=conn_check)
    cm_check.__exit__ = MagicMock(return_value=False)

    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.side_effect = [cm_main, cm_check]
        from app.exceptions.forge_error import ForgeError
        with pytest.raises(ForgeError) as exc_info:
            svc.list_columns(workspace_id="ws-1", workspace_table_id=999, q=None, active_only=True)
    assert exc_info.value.status_code == 404


def test_list_columns_empty_table_returns_200(svc):
    """Table exists in workspace but has zero columns — should return empty rows, not 404."""
    conn_main, cm_main = _make_conn([])
    # Existence check returns a row (table is found)
    conn_check = MagicMock()
    conn_check.execute.return_value.fetchone.return_value = (1,)
    cm_check = MagicMock()
    cm_check.__enter__ = MagicMock(return_value=conn_check)
    cm_check.__exit__ = MagicMock(return_value=False)

    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.side_effect = [cm_main, cm_check]
        result = svc.list_columns(
            workspace_id="ws-1", workspace_table_id=42, q=None, active_only=True
        )
    assert result["rows"] == []


def test_search_columns_matches_column_name(svc):
    raw = [{
        "id": 5, "workspace_table_id": 1, "column_name": "npi",
        "data_type": "string", "ordinal_position": 1,
        "description": None, "is_active": 1,
        "semantic_type": None, "semantic_entity": None,
        "semantic_sub_type": None, "semantic_confidence": None,
        "sample_values_json": None, "sample_stats_json": None,
        "sample_ran_at": None, "sample_error": None,
        "table_name": "dim_prov", "full_name": "asset.dim_prov",
    }]
    conn, cm = _make_conn(raw)
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.search_columns(workspace_id="ws-1", q="npi", limit=200, active_only=True)
    assert result["rows"][0]["column_name"] == "npi"


def test_patch_column_updates_description(svc):
    updated_row = {
        "id": 5, "workspace_table_id": 1, "column_name": "npi",
        "data_type": "string", "ordinal_position": 1,
        "description": "Updated", "is_active": 1,
        "semantic_type": None, "semantic_entity": None,
        "semantic_sub_type": None, "semantic_confidence": None,
        "sample_values_json": None, "sample_stats_json": None,
        "sample_ran_at": None, "sample_error": None,
        "table_name": "dim_prov", "full_name": "asset.dim_prov",
    }
    conn, cm = _make_conn([updated_row])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.patch_column(
            workspace_id="ws-1",
            column_id=5,
            patch={"description": "Updated"},
        )
    assert result["row"]["description"] == "Updated"


def test_patch_column_404_for_wrong_workspace(svc):
    conn, cm = _make_conn([])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        from app.exceptions.forge_error import ForgeError
        with pytest.raises(ForgeError) as exc_info:
            svc.patch_column(workspace_id="ws-other", column_id=5, patch={"description": "x"})
    assert exc_info.value.status_code == 404


def test_import_columns_returns_updated_and_unmatched(svc):
    rows = [
        {"table_name": "dim_prov", "column_name": "npi", "description": "NPI", "data_type": None},
        {"table_name": "dim_prov", "column_name": "MISSING", "description": "x", "data_type": None},
    ]
    # First execute call (full_replace=False, so no clear): UPDATE returns rowcount 1 for npi, 0 for MISSING
    conn = MagicMock()
    result_npi = MagicMock()
    result_npi.rowcount = 1
    result_miss = MagicMock()
    result_miss.rowcount = 0
    conn.execute.side_effect = [result_npi, result_miss]
    conn.commit = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.import_columns(workspace_id="ws-1", rows=rows, full_replace=False)

    assert result["updated"] == 1
    assert len(result["unmatched"]) == 1
    assert result["unmatched"][0]["column_name"] == "MISSING"


def test_import_columns_full_replace_clears_first(svc):
    """When full_replace=True the clear SQL must execute before any row updates."""
    rows = [{"table_name": "dim_prov", "column_name": "npi", "description": "NPI", "data_type": None}]
    conn = MagicMock()
    result_clear = MagicMock()
    result_clear.rowcount = 0
    result_update = MagicMock()
    result_update.rowcount = 1
    conn.execute.side_effect = [result_clear, result_update]
    conn.commit = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.import_columns(workspace_id="ws-1", rows=rows, full_replace=True)

    # Two execute calls: clear + update (not just one update)
    assert conn.execute.call_count == 2
    assert result["updated"] == 1
    assert result["unmatched"] == []


def test_patch_column_accepts_semantic_type(svc):
    updated_row = {
        "id": 5, "workspace_table_id": 1, "column_name": "npi",
        "data_type": "string", "ordinal_position": 1,
        "description": None, "is_active": 1,
        "semantic_type": "Identifier", "semantic_entity": None,
        "semantic_sub_type": None, "semantic_confidence": None,
        "sample_values_json": None, "sample_stats_json": None,
        "sample_ran_at": None, "sample_error": None,
        "table_name": "dim_prov", "full_name": "asset.dim_prov",
    }
    conn, cm = _make_conn([updated_row])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.patch_column(
            workspace_id="ws-1",
            column_id=5,
            patch={"semantic_type": "Identifier"},
        )
    assert result["row"]["semantic_type"] == "Identifier"
    # Verify the UPDATE execute call actually received semantic_type in its params
    assert conn.execute.call_count == 2  # call 0 = UPDATE, call 1 = SELECT (patch_column uses two engine.connect() blocks)
    first_call_params = conn.execute.call_args_list[0][0][1]
    assert first_call_params.get("semantic_type") == "Identifier"


def test_patch_column_accepts_semantic_confidence(svc):
    updated_row = {
        "id": 5, "workspace_table_id": 1, "column_name": "npi",
        "data_type": "string", "ordinal_position": 1,
        "description": None, "is_active": 1,
        "semantic_type": None, "semantic_entity": None,
        "semantic_sub_type": None, "semantic_confidence": 0.92,
        "sample_values_json": None, "sample_stats_json": None,
        "sample_ran_at": None, "sample_error": None,
        "table_name": "dim_prov", "full_name": "asset.dim_prov",
    }
    conn, cm = _make_conn([updated_row])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.patch_column(
            workspace_id="ws-1",
            column_id=5,
            patch={"semantic_confidence": 0.92},
        )
    assert result["row"]["semantic_confidence"] == 0.92
    # Verify the UPDATE execute call actually received semantic_confidence in its params
    assert conn.execute.call_count == 2  # call 0 = UPDATE, call 1 = SELECT (patch_column uses two engine.connect() blocks)
    first_call_params = conn.execute.call_args_list[0][0][1]
    assert first_call_params.get("semantic_confidence") == 0.92


def test_patch_column_rejects_unknown_fields(svc):
    """Fields not in _ALLOWED_PATCH_FIELDS must raise 400, not silently drop."""
    from app.exceptions.forge_error import ForgeError
    with pytest.raises(ForgeError) as exc_info:
        svc.patch_column(
            workspace_id="ws-1",
            column_id=5,
            patch={"not_a_real_field": "value"},
        )
    assert exc_info.value.status_code == 400


def test_patch_table_updates_description(svc):
    updated_row = {
        "id": 1, "table_name": "dim_prov", "full_name": "asset.dim_prov",
        "schema_name": "asset", "catalog_name": None, "description": "Updated desc",
    }
    conn, cm = _make_conn([updated_row])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.patch_table(
            workspace_id="ws-1",
            table_id=1,
            patch={"description": "Updated desc"},
        )
    assert result["row"]["description"] == "Updated desc"
    assert result["row"]["table_name"] == "dim_prov"
    # Must return all 6 DictionaryTableRow fields
    for field in ("id", "table_name", "full_name", "schema_name", "catalog_name", "description"):
        assert field in result["row"]


def test_patch_table_404_for_wrong_workspace(svc):
    conn, cm = _make_conn([])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        from app.exceptions.forge_error import ForgeError
        with pytest.raises(ForgeError) as exc_info:
            svc.patch_table(workspace_id="ws-other", table_id=1, patch={"description": "x"})
    assert exc_info.value.status_code == 404


def test_patch_table_400_for_empty_patch(svc):
    from app.exceptions.forge_error import ForgeError
    with pytest.raises(ForgeError) as exc_info:
        svc.patch_table(workspace_id="ws-1", table_id=1, patch={})
    assert exc_info.value.status_code == 400


def test_patch_table_accepts_null_description(svc):
    """description: null is valid — it clears the field (sets NULL in the DB)."""
    updated_row = {
        "id": 1, "table_name": "dim_prov", "full_name": "asset.dim_prov",
        "schema_name": "asset", "catalog_name": None, "description": None,
    }
    conn, cm = _make_conn([updated_row])
    with patch("app.services.dictionary.dictionary_service.engine") as mock_engine:
        mock_engine.connect.return_value = cm
        result = svc.patch_table(
            workspace_id="ws-1",
            table_id=1,
            patch={"description": None},
        )
    assert result["row"]["description"] is None
    # Verify None was passed to SQL (not filtered out)
    assert conn.execute.call_count == 2  # call 0 = UPDATE, call 1 = SELECT (patch_table uses two engine.connect() blocks; mock reuses same conn)
    first_call_params = conn.execute.call_args_list[0][0][1]
    assert "description" in first_call_params
    assert first_call_params["description"] is None

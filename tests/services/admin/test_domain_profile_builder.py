from __future__ import annotations

import json

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.admin.domain_profile_builder import DomainProfileBuilder


class _FakeSQL:
    def __init__(self, *, has_domain: bool = True) -> None:
        self.has_domain = has_domain

    def execute_query_mappings(self, query: str, params=None):
        del params
        if "FROM domain d" in query and "LIMIT 1" in query:
            if not self.has_domain:
                return []
            return [
                {
                    "domain_id": 15,
                    "workspace_id": "ws-1",
                    "domain_name": "ADM",
                    "domain_description": "Average Daily Membership",
                    "domain_kind": "education",
                    "domain_is_active": 1,
                }
            ]
        if "JOIN workspace_column wc" in query:
            return [
                {
                    "workspace_table_id": 34,
                    "column_name": "normalized_adm",
                    "data_type": "double",
                    "nullable": 1,
                    "ordinal_position": 1,
                    "semantic_type": "metric",
                    "description": "Normalized ADM",
                },
                {
                    "workspace_table_id": 20,
                    "column_name": "school_name",
                    "data_type": "string",
                    "nullable": 1,
                    "ordinal_position": 1,
                    "semantic_type": "entity",
                    "description": "School Name",
                },
            ]
        if "FROM domain_workspace_table dwt" in query and "JOIN workspace_table wt" in query:
            return [
                {
                    "domain_id": 15,
                    "workspace_table_id": 34,
                    "role": "fact",
                    "is_primary": 1,
                    "relation_kind": "base",
                    "sort_order": 0,
                    "table_alias": "adm",
                    "filter_mode": None,
                    "cardinality": "many_to_one",
                    "table_name": "fct_student_base_adm",
                    "full_name": "teds_prod.edfi_wh.fct_student_base_adm",
                    "catalog_name": "teds_prod",
                    "schema_name": "edfi_wh",
                    "variant_code": None,
                    "exists_in_dbx": 1,
                    "model_table_id": 100,
                    "source_table_name": "fct_student_base_adm",
                    "table_description": "Student ADM fact table",
                },
                {
                    "domain_id": 15,
                    "workspace_table_id": 20,
                    "role": "dimension",
                    "is_primary": 0,
                    "relation_kind": "lookup",
                    "sort_order": 1,
                    "table_alias": "school",
                    "filter_mode": None,
                    "cardinality": "many_to_one",
                    "table_name": "dim_school",
                    "full_name": "teds_prod.edfi_wh.dim_school",
                    "catalog_name": "teds_prod",
                    "schema_name": "edfi_wh",
                    "variant_code": None,
                    "exists_in_dbx": 1,
                    "model_table_id": 101,
                    "source_table_name": "dim_school",
                    "table_description": "School dimension",
                },
            ]
        if "FROM domain_table_join dtj" in query:
            return [
                {
                    "id": "join-1",
                    "domain_id": 15,
                    "from_workspace_table_id": 34,
                    "to_workspace_table_id": 20,
                    "join_type": "LEFT",
                    "join_spec_json": json.dumps(
                        {
                            "clauses": [
                                {
                                    "left": "{from}.k_school",
                                    "op": "=",
                                    "right": "{to}.k_school",
                                }
                            ]
                        }
                    ),
                    "sort_order": 0,
                    "is_active": 1,
                    "from_table_name": "fct_student_base_adm",
                    "to_table_name": "dim_school",
                }
            ]
        return []


def test_build_domain_context_includes_tables_columns_and_joins():
    svc = DomainProfileBuilder(sql=_FakeSQL())

    out = svc.build_domain_context(workspace_id="ws-1", domain_id=15)

    assert out["domain"]["name"] == "ADM"
    assert out["stats"]["table_count"] == 2
    assert out["stats"]["column_count"] == 2
    assert out["stats"]["join_count"] == 1
    assert out["tables"][0]["workspace_table_id"] == 34
    assert out["tables"][0]["columns"][0]["column_name"] == "normalized_adm"
    assert "LEFT JOIN" in out["relationship_lines"][0]


def test_build_domain_context_raises_404_when_missing():
    svc = DomainProfileBuilder(sql=_FakeSQL(has_domain=False))

    with pytest.raises(ForgeError) as exc:
        svc.build_domain_context(workspace_id="ws-1", domain_id=999)

    assert exc.value.status_code == 404

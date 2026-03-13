from __future__ import annotations

import json

from app.services.semantic.catalog.catalog_models import ColumnProfile
from app.services.semantic.catalog.column_profile_builder import ColumnProfileBuilder
from app.services.semantic.catalog.semantic_catalog_builder import SemanticCatalogBuilder
from app.services.semantic.catalog.semantic_enrichment_service import SemanticEnrichmentService


class _FakeSQL:
    def __init__(self, rows):
        self._rows = list(rows)

    def execute_query_mappings(self, query, params=None):
        del query, params
        return list(self._rows)


class _ProfileStub:
    def __init__(self, profiles):
        self._profiles = list(profiles)

    def build_profiles(self, **kwargs):
        del kwargs
        return list(self._profiles)


class _FailingLLM:
    def enrich_batch(self, **kwargs):
        del kwargs
        raise RuntimeError("llm unavailable")


def test_column_profile_builder_infers_flags_and_stats() -> None:
    stats = {
        "row_count": 1000,
        "distinct_count": 995,
        "min_value": 1,
        "max_value": 999,
    }
    fake_rows = [
        {
            "workspace_table_id": 187,
            "workspace_column_id": 9805,
            "table_name": "dim_sales_rep",
            "column_name": "sales_rep_id",
            "data_type": "BIGINT",
            "nullable": 0,
            "sample_values_json": json.dumps(["1", "2", "3"]),
            "sample_stats_json": json.dumps(stats),
        }
    ]
    builder = ColumnProfileBuilder(sql=_FakeSQL(fake_rows))
    profiles = builder.build_profiles(workspace_id="ws_1", domain_id=3)

    assert len(profiles) == 1
    p = profiles[0]
    assert p.workspace_table_id == 187
    assert p.row_count == 1000
    assert p.distinct_count == 995
    assert p.is_numeric is True
    assert p.is_identifier is True
    assert p.is_measure_candidate is False


def test_semantic_enrichment_service_falls_back_to_heuristics_when_llm_fails() -> None:
    profiles = [
        ColumnProfile(
            workspace_table_id=1,
            workspace_column_id=1,
            table_name="fct_sales",
            column_name="sales_amount",
            data_type="DECIMAL(18,2)",
            nullable=False,
            distinct_count=300,
            row_count=1000,
            sample_values=["100.0", "200.0"],
            is_identifier=False,
            is_numeric=True,
            is_date_like=False,
            is_enum_like=False,
            is_dimension_candidate=False,
            is_measure_candidate=True,
        )
    ]
    svc = SemanticEnrichmentService(llm_adapter=_FailingLLM(), enable_llm=True, batch_size=5)
    enriched = svc.enrich_profiles(
        profiles=profiles,
        workspace_id="ws-test",
        vertical_norm="generic",
        domain_name="Sales Performance",
    )

    assert len(enriched) == 1
    assert enriched[0].enrichment.semantic_type in {"measure", "metric"}
    assert "sum" in enriched[0].enrichment.default_aggregations


def test_semantic_catalog_builder_sales_example_generates_expected_derived_metrics_dry_run() -> None:
    profiles = [
        ColumnProfile(
            workspace_table_id=10,
            workspace_column_id=1,
            table_name="fct_sales",
            column_name="sales_amount",
            data_type="DECIMAL",
            nullable=False,
            is_numeric=True,
            is_measure_candidate=True,
        ),
        ColumnProfile(
            workspace_table_id=10,
            workspace_column_id=2,
            table_name="fct_sales",
            column_name="quota_amount",
            data_type="DECIMAL",
            nullable=False,
            is_numeric=True,
            is_measure_candidate=True,
        ),
        ColumnProfile(
            workspace_table_id=10,
            workspace_column_id=3,
            table_name="fct_sales",
            column_name="discount_amount",
            data_type="DECIMAL",
            nullable=False,
            is_numeric=True,
            is_measure_candidate=True,
        ),
        ColumnProfile(
            workspace_table_id=10,
            workspace_column_id=4,
            table_name="fct_sales",
            column_name="order_count",
            data_type="BIGINT",
            nullable=False,
            is_numeric=True,
            is_measure_candidate=True,
        ),
        ColumnProfile(
            workspace_table_id=11,
            workspace_column_id=5,
            table_name="dim_sales_rep",
            column_name="sales_rep_name",
            data_type="STRING",
            nullable=True,
            is_dimension_candidate=True,
        ),
        ColumnProfile(
            workspace_table_id=11,
            workspace_column_id=6,
            table_name="dim_territory",
            column_name="territory_name",
            data_type="STRING",
            nullable=True,
            is_dimension_candidate=True,
        ),
        ColumnProfile(
            workspace_table_id=12,
            workspace_column_id=7,
            table_name="dim_calendar",
            column_name="order_date",
            data_type="DATE",
            nullable=True,
            is_date_like=True,
            is_dimension_candidate=True,
        ),
    ]

    builder = SemanticCatalogBuilder(
        profile_builder=_ProfileStub(profiles),
        enrichment_service=SemanticEnrichmentService(enable_llm=False),
    )
    result = builder.run_sales_performance_example(
        workspace_id="ws_1",
        domain_id=3,
        vertical_norm="generic",
        dry_run=True,
    )

    keys = {str(row.get("concept_key") or "") for row in result.concept_preview}
    assert "QUOTA_ATTAINMENT_PCT" in keys
    assert "AVERAGE_ORDER_VALUE" in keys
    assert "DISCOUNT_RATE" in keys
    assert result.derived_metrics_created >= 3
    assert result.relationships_upserted > 0

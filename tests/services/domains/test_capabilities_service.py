from __future__ import annotations

from app.services.domains.capabilities_service import DomainCapabilitiesService


class _FakeSQL:
    pass


def test_build_domain_metrics_preserves_sql_metric_payload() -> None:
    svc = DomainCapabilitiesService(sql=_FakeSQL())
    metrics = svc._build_domain_metrics(
        [
            {
                "metric_key": "adm_total",
                "label": "Total ADM",
                "kind": "sum",
                "agg": "sum",
                "column_key": "wt31.normalized_adm",
                "sql_metric": {
                    "fn": "sum",
                    "field": {
                        "workspaceTableId": 31,
                        "modelColumnId": 900,
                        "columnName": "normalized_adm",
                    },
                },
            }
        ]
    )
    assert metrics
    first = metrics[0]
    assert first["metric_key"] == "adm_total"
    assert first["sql_metric"]["fn"] == "sum"
    assert first["sql_metric"]["field"]["columnName"] == "normalized_adm"

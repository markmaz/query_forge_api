from __future__ import annotations

from app.services.domain.summary.domain_summary_collapser import collapse_domain_summary_rows


def test_collapse_domain_summary_rows_groups_samples_per_domain() -> None:
    out = collapse_domain_summary_rows(
        [
            {"domain_id": 1, "table_count": 2, "sample_table_name": "a"},
            {"domain_id": 1, "table_count": 2, "sample_table_name": "b"},
            {"domain_id": 2, "table_count": 0, "sample_table_name": None},
        ]
    )

    assert out == [
        {"id": 1, "table_count": 2, "table_sample": ["a", "b"]},
        {"id": 2, "table_count": 0, "table_sample": []},
    ]

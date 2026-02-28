from __future__ import annotations

from app.services.planner_llm.service import PlannerLLMCandidateRetriever


def test_shape_columns_keeps_top_n_per_table_instead_of_aggressive_global_collapse() -> None:
    rows = [
        {"column_key": "wt1.a", "table": "t1", "_score": 0.99},
        {"column_key": "wt1.b", "table": "t1", "_score": 0.97},
        {"column_key": "wt1.c", "table": "t1", "_score": 0.96},
        {"column_key": "wt2.a", "table": "t2", "_score": 0.95},
        {"column_key": "wt2.b", "table": "t2", "_score": 0.94},
        {"column_key": "wt3.a", "table": "t3", "_score": 0.93},
    ]
    shaped = PlannerLLMCandidateRetriever._shape_columns_with_per_table_cap(
        rows=rows,
        max_columns=5,
        per_table_cap=2,
    )

    keys = [item["column_key"] for item in shaped]
    assert "wt1.a" in keys
    assert "wt1.b" in keys
    assert "wt1.c" not in keys
    assert "wt2.a" in keys
    assert "wt2.b" in keys
    # no table completely starved
    assert any(item["table"] == "t3" for item in shaped)

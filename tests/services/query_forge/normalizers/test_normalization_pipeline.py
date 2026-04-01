"""Phase 4 — tests for app/services/query_forge/normalizers/__init__.py (NormalizationPipeline)."""
from __future__ import annotations

from typing import Any


def _noop(*, query_json, domain_columns, **_extra):
    return dict(query_json), [], {}


def _add_issue(issue: str):
    def _fn(*, query_json, domain_columns, **_extra):
        return dict(query_json), [issue], {"applied": 1}
    return _fn


def _append_to_query(key: str, value: Any):
    def _fn(*, query_json, domain_columns, **_extra):
        out = dict(query_json)
        out[key] = value
        return out, [], {}
    return _fn


class TestNormalizationPipeline:
    def test_empty_pipeline_returns_query_unchanged(self):
        from app.services.query_forge.normalizers import NormalizationPipeline

        pipeline = NormalizationPipeline(normalizers=[])
        result = pipeline.run(query_json={"intent": "list"}, domain_columns={})
        assert result.query_json == {"intent": "list"}
        assert result.all_issues == []
        assert result.debug == {}

    def test_threads_plan_through_normalizers_in_order(self):
        from app.services.query_forge.normalizers import NormalizationPipeline

        pipeline = NormalizationPipeline(
            normalizers=[
                ("step_a", _append_to_query("a", 1)),
                ("step_b", _append_to_query("b", 2)),
            ]
        )
        result = pipeline.run(query_json={}, domain_columns={})
        assert result.query_json["a"] == 1
        assert result.query_json["b"] == 2

    def test_normalizers_see_output_of_previous_step(self):
        from app.services.query_forge.normalizers import NormalizationPipeline

        seen: list[dict] = []

        def _capture(*, query_json, domain_columns, **_extra):
            seen.append(dict(query_json))
            out = dict(query_json)
            out["step_count"] = out.get("step_count", 0) + 1
            return out, [], {}

        pipeline = NormalizationPipeline(normalizers=[("s1", _capture), ("s2", _capture)])
        result = pipeline.run(query_json={}, domain_columns={})
        assert result.query_json["step_count"] == 2
        assert seen[0].get("step_count", 0) == 0
        assert seen[1]["step_count"] == 1

    def test_aggregates_issues_from_all_normalizers(self):
        from app.services.query_forge.normalizers import NormalizationPipeline

        pipeline = NormalizationPipeline(
            normalizers=[
                ("col", _add_issue("col_normalized")),
                ("filter", _add_issue("filter_normalized")),
            ]
        )
        result = pipeline.run(query_json={}, domain_columns={})
        assert "col_normalized" in result.all_issues
        assert "filter_normalized" in result.all_issues

    def test_noop_normalizer_contributes_no_issues(self):
        from app.services.query_forge.normalizers import NormalizationPipeline

        pipeline = NormalizationPipeline(normalizers=[("noop", _noop)])
        result = pipeline.run(query_json={}, domain_columns={})
        assert result.all_issues == []

    def test_collects_debug_by_normalizer_name(self):
        from app.services.query_forge.normalizers import NormalizationPipeline

        pipeline = NormalizationPipeline(
            normalizers=[("col", _add_issue("col_normalized")), ("noop", _noop)]
        )
        result = pipeline.run(query_json={}, domain_columns={})
        assert "col" in result.debug
        assert result.debug["col"]["applied"] == 1
        assert "noop" not in result.debug

    def test_result_is_normalization_pipeline_result(self):
        from app.services.query_forge.normalizers import NormalizationPipeline, NormalizationPipelineResult

        pipeline = NormalizationPipeline(normalizers=[("step", _noop)])
        result = pipeline.run(query_json={"x": 1}, domain_columns={})
        assert isinstance(result, NormalizationPipelineResult)
        assert result.query_json["x"] == 1

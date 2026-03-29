"""Unit tests for app.services.planner_domain.pipeline_trace."""
from app.services.planner_domain.pipeline_trace import (
    _add_pipeline_step,
    _append_pipeline_trace_step,
    _elapsed_ms,
    _read_pipeline_profile_from_log,
)
from time import perf_counter


def test_elapsed_ms_returns_int():
    start = perf_counter()
    result = _elapsed_ms(start)
    assert isinstance(result, int)
    assert result >= 0


def test_add_pipeline_step_disabled():
    result = _add_pipeline_step(
        profile_steps=[],
        enabled=False,
        step="test",
        label="Test step",
        started_at=perf_counter(),
    )
    assert isinstance(result, int)


def test_append_pipeline_trace_step_disabled():
    trace = []
    _append_pipeline_trace_step(trace=trace, enabled=False, step="test", data={})
    assert trace == []


def test_read_pipeline_profile_from_log_missing_file():
    result = _read_pipeline_profile_from_log(trace_id="nonexistent-trace-id")
    assert result is None

from __future__ import annotations

import app.services.planner_domain.service as planner_domain_service_module
from app.exceptions.service_error import ServiceError
from app.services.planner_domain.service import _read_pipeline_profile_from_log


def test_read_pipeline_profile_from_log_returns_latest_match(monkeypatch, tmp_path) -> None:
    log_file = tmp_path / "plan_domain_pipeline_timing.log"
    log_file.write_text(
        (
            "2026-03-04 10:00:00,000 [INFO] planner_domain.pipeline_profile - "
            "plan_domain_pipeline trace_id=trace-abc workspace_id=ws-1 user_id=user-1 "
            "conversation_id=pdc_1 total_ms=120\n"
            "prompt=old prompt\n"
            "1. Domain selection: 20ms\n"
            "2026-03-04 10:01:00,000 [INFO] planner_domain.pipeline_profile - "
            "plan_domain_pipeline trace_id=trace-abc workspace_id=ws-1 user_id=user-1 "
            "conversation_id=pdc_2 total_ms=240\n"
            "prompt=new prompt\n"
            "1. Domain selection: 40ms\n"
            "2. Generate PlanV2 with LLM: 180ms\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE", str(log_file))

    out = _read_pipeline_profile_from_log(
        trace_id="trace-abc",
        workspace_id="ws-1",
        user_id="user-1",
    )

    assert out["trace_id"] == "trace-abc"
    assert out["conversation_id"] == "pdc_2"
    assert out["total_ms"] == 240
    assert out["prompt"] == "new prompt"
    assert len(list(out.get("steps") or [])) == 2


def test_read_pipeline_profile_from_log_respects_workspace_and_user(monkeypatch, tmp_path) -> None:
    log_file = tmp_path / "plan_domain_pipeline_timing.log"
    log_file.write_text(
        (
            "2026-03-04 10:00:00,000 [INFO] planner_domain.pipeline_profile - "
            "plan_domain_pipeline trace_id=trace-xyz workspace_id=ws-2 user_id=user-9 "
            "conversation_id=pdc_1 total_ms=120\n"
            "prompt=prompt\n"
            "1. Domain selection: 20ms\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE", str(log_file))

    try:
        _read_pipeline_profile_from_log(
            trace_id="trace-xyz",
            workspace_id="ws-1",
            user_id="user-1",
        )
    except ServiceError as exc:
        assert exc.status_code == 404
        assert "trace-xyz" in str(exc.details or {})
    else:
        raise AssertionError("Expected ServiceError for workspace/user mismatch")

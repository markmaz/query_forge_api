from __future__ import annotations

import os
import tempfile

import pytest


SAMPLE_LOG = """\
2026-03-04 10:00:00,100 [INFO] planner_domain.pipeline_profile - plan_domain_pipeline trace_id=aaa-111 workspace_id=ws-1 user_id=user-1 conversation_id=pdc_conv1 total_ms=800
prompt=show me attendance by school
1. Load context: 5ms
2. Domain selection: 45ms
3. LLM plan generation: 700ms
4. Validation: 50ms
2026-03-04 10:01:00,200 [INFO] planner_domain.pipeline_profile - plan_domain_pipeline trace_id=bbb-222 workspace_id=ws-1 user_id=user-1 conversation_id=pdc_conv2 total_ms=500
prompt=students per teacher by county
1. Load context: 3ms
2. Domain selection: 30ms
3. LLM plan generation: 400ms
4. Validation: 67ms
2026-03-04 10:02:00,300 [INFO] planner_domain.pipeline_profile - plan_domain_pipeline trace_id=ccc-333 workspace_id=ws-2 user_id=user-2 conversation_id=pdc_conv3 total_ms=1200
prompt=enrollment by grade level
1. Load context: 10ms
2. Domain selection: 90ms
3. LLM plan generation: 1000ms
4. Validation: 100ms
"""


def test_list_pipeline_profiles_from_log(monkeypatch):
    from app.services.planner_domain import service as svc_mod

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name

    try:
        monkeypatch.setattr(svc_mod, "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE", log_path)
        result = svc_mod._list_pipeline_profiles_from_log(limit=50)
        assert len(result) == 3
        assert result[0]["trace_id"] == "ccc-333"
        assert result[1]["trace_id"] == "bbb-222"
        assert result[2]["trace_id"] == "aaa-111"
    finally:
        os.unlink(log_path)


def test_list_pipeline_profiles_respects_limit(monkeypatch):
    from app.services.planner_domain import service as svc_mod

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name

    try:
        monkeypatch.setattr(svc_mod, "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE", log_path)
        result = svc_mod._list_pipeline_profiles_from_log(limit=2)
        assert len(result) == 2
    finally:
        os.unlink(log_path)


def test_list_pipeline_profiles_empty_when_no_log(monkeypatch):
    from app.services.planner_domain import service as svc_mod

    monkeypatch.setattr(svc_mod, "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE", "/nonexistent/path.log")
    result = svc_mod._list_pipeline_profiles_from_log(limit=50)
    assert result == []


def test_list_pipeline_profiles_has_steps(monkeypatch):
    from app.services.planner_domain import service as svc_mod

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name

    try:
        monkeypatch.setattr(svc_mod, "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE", log_path)
        result = svc_mod._list_pipeline_profiles_from_log(limit=50)
        first = result[0]
        assert first["total_ms"] == 1200
        assert len(first["steps"]) == 4
        assert first["steps"][0]["label"] == "Load context"
        assert first["prompt"] == "enrollment by grade level"
    finally:
        os.unlink(log_path)

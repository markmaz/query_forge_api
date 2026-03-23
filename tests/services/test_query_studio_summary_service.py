from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

import app.services.query_studio_summary_service as svc_module
from app.services.query_studio_summary_service import generate_preview_summary
from app.exceptions.llm_unavailable_error import LLMUnavailableError


ROWS_10 = [{"col": str(i)} for i in range(10)]
ROWS_150 = [{"col": str(i)} for i in range(150)]

LLM_RESPONSE = {
    "narrative": "Test narrative.",
    "highlights": ["highlight 1", "highlight 2"],
    "comparison": None,
}


def _patch_llm(result=None, side_effect=None):
    """Patch call_analysis_llm and both prompt builders."""
    return [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(
            svc_module, "call_analysis_llm",
            return_value=result or LLM_RESPONSE,
            side_effect=side_effect,
        ),
    ]


def _apply_patches(patches):
    for p in patches:
        p.start()
    return patches


def _stop_patches(patches):
    for p in patches:
        p.stop()


# Happy path

def test_happy_path_returns_normalized_fields():
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "My Query", ["col"], ROWS_10)
        assert result == {
            "narrative": "Test narrative.",
            "highlights": ["highlight 1", "highlight 2"],
            "comparison": None,
            "capped": False,
        }
    finally:
        _stop_patches(patches)


def test_capped_false_when_rows_under_max():
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["capped"] is False
    finally:
        _stop_patches(patches)


def test_capped_true_when_rows_exceed_max(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_150)
        assert result["capped"] is True
    finally:
        _stop_patches(patches)


def test_only_max_rows_sent_to_llm(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"), \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr") as mock_user_prompt, \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_150)
        call_kwargs = mock_user_prompt.call_args
        # rows is the 4th positional arg or a keyword arg
        rows_passed = (
            call_kwargs.kwargs.get("rows")
            if call_kwargs.kwargs.get("rows") is not None
            else call_kwargs.args[3]
        )
        assert len(rows_passed) == 100


def test_original_row_count_passed_to_user_prompt(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"), \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr") as mock_user_prompt, \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_150)
        call_kwargs = mock_user_prompt.call_args
        row_count = (
            call_kwargs.kwargs.get("row_count")
            if "row_count" in (call_kwargs.kwargs or {})
            else call_kwargs.args[2]
        )
        assert row_count == 150


def test_cap_disclaimer_appended_to_prompt_hint(monkeypatch):
    monkeypatch.setenv("QUERY_STUDIO_SUMMARY_MAX_ROWS", "100")
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys") as mock_sys, \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"), \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_150, prompt_hint="focus on revenue")
        hint_used = (
            mock_sys.call_args.kwargs.get("hint")
            if "hint" in (mock_sys.call_args.kwargs or {})
            else mock_sys.call_args.args[0]
        )
        assert "100 rows of 150 total" in hint_used
        assert "focus on revenue" in hint_used


def test_include_comparison_false_passed_to_system_prompt():
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys") as mock_sys, \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"), \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert mock_sys.call_args.kwargs.get("include_comparison") is False


def test_previous_highlights_and_run_date_are_none():
    with patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"), \
         patch.object(svc_module, "build_analysis_user_prompt", return_value="usr") as mock_user, \
         patch.object(svc_module, "call_analysis_llm", return_value=LLM_RESPONSE):
        generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        kwargs = mock_user.call_args.kwargs
        assert kwargs.get("previous_highlights") is None
        assert kwargs.get("previous_run_date") is None


def test_empty_rows_accepted_capped_false():
    patches = _apply_patches(_patch_llm())
    try:
        result = generate_preview_summary("ws-1", "Q", [], [])
        assert result["capped"] is False
    finally:
        _stop_patches(patches)


# Error handling

def test_llm_unavailable_raises_llm_unavailable_error_404():
    """ForgeError 404 = no LLM config found → LLMUnavailableError."""
    from app.exceptions.forge_error import ForgeError
    patches = [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(svc_module, "call_analysis_llm", side_effect=ForgeError("No LLM", status_code=404)),
    ]
    _apply_patches(patches)
    try:
        with pytest.raises(LLMUnavailableError):
            generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
    finally:
        _stop_patches(patches)


def test_llm_unavailable_raises_llm_unavailable_error_400():
    """ForgeError 400 = LLM misconfigured → LLMUnavailableError."""
    from app.exceptions.forge_error import ForgeError
    patches = [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(svc_module, "call_analysis_llm", side_effect=ForgeError("LLM model_name is not configured", status_code=400)),
    ]
    _apply_patches(patches)
    try:
        with pytest.raises(LLMUnavailableError):
            generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
    finally:
        _stop_patches(patches)


def test_llm_failure_propagates():
    patches = [
        patch.object(svc_module, "build_analysis_system_prompt", return_value="sys"),
        patch.object(svc_module, "build_analysis_user_prompt", return_value="usr"),
        patch.object(svc_module, "call_analysis_llm", side_effect=RuntimeError("LLM exploded")),
    ]
    _apply_patches(patches)
    try:
        with pytest.raises(RuntimeError, match="LLM exploded"):
            generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
    finally:
        _stop_patches(patches)


# Normalization

def test_normalizes_missing_highlights_to_empty_list():
    llm_resp = {"narrative": "text", "comparison": None}
    patches = _apply_patches(_patch_llm(result=llm_resp))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["highlights"] == []
    finally:
        _stop_patches(patches)


def test_normalizes_none_highlights_to_empty_list():
    llm_resp = {"narrative": "text", "highlights": None, "comparison": None}
    patches = _apply_patches(_patch_llm(result=llm_resp))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["highlights"] == []
    finally:
        _stop_patches(patches)


def test_normalizes_missing_narrative_to_empty_string():
    llm_resp = {"highlights": ["h1"], "comparison": None}
    patches = _apply_patches(_patch_llm(result=llm_resp))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["narrative"] == ""
    finally:
        _stop_patches(patches)


def test_comparison_passed_through_null():
    patches = _apply_patches(_patch_llm(result={**LLM_RESPONSE, "comparison": None}))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["comparison"] is None
    finally:
        _stop_patches(patches)


def test_comparison_passed_through_string():
    patches = _apply_patches(_patch_llm(result={**LLM_RESPONSE, "comparison": "Up 10%"}))
    try:
        result = generate_preview_summary("ws-1", "Q", ["col"], ROWS_10)
        assert result["comparison"] == "Up 10%"
    finally:
        _stop_patches(patches)

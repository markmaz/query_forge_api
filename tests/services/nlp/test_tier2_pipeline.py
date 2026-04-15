from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import sys

import pytest

import app.nlp.tier2_spacy.pipeline as pipeline


def test_tier2_parse_basic_name_phrase(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "NLP_TIER2_ENABLED", True)
    monkeypatch.setattr(pipeline, "_load_model", lambda: None)

    result = pipeline.run_tier2("Find all the students named Holden")

    payload = result.model_dump(mode="json")
    assert payload["entities"]["subject_entity"] == "student"
    names = payload["slots"]["names"]
    assert any(str(item.get("value") or "").lower() == "holden" for item in names)


def test_tier2_school_phrase(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "NLP_TIER2_ENABLED", True)
    monkeypatch.setattr(pipeline, "_load_model", lambda: None)

    result = pipeline.run_tier2(
        "Give me all the first and last names of all students at the Clarksville Elementary School"
    )

    payload = result.model_dump(mode="json")
    schools = payload["slots"]["school"]
    assert any("clarksville elementary school" in str(item.get("value") or "").lower() for item in schools)


def test_run_tier2_marks_warning_for_expected_inference_errors(monkeypatch) -> None:
    class _BrokenNlp:
        def __call__(self, text):
            raise RuntimeError("tier2 unavailable")

    monkeypatch.setattr(pipeline, "NLP_TIER2_ENABLED", True)
    monkeypatch.setattr(
        pipeline,
        "_load_model",
        lambda: pipeline._LoadedModel(nlp=_BrokenNlp(), model_version="test-model"),
    )

    result = pipeline.run_tier2("Find students named Holden")
    payload = result.model_dump(mode="json")

    assert "tier2_inference_error" in payload["warnings"]


def test_run_tier2_surfaces_unexpected_inference_errors(monkeypatch) -> None:
    class _BrokenNlp:
        def __call__(self, text):
            raise AssertionError("unexpected inference bug")

    monkeypatch.setattr(pipeline, "NLP_TIER2_ENABLED", True)
    monkeypatch.setattr(
        pipeline,
        "_load_model",
        lambda: pipeline._LoadedModel(nlp=_BrokenNlp(), model_version="test-model"),
    )

    with pytest.raises(AssertionError, match="unexpected inference bug"):
        pipeline.run_tier2("Find students named Holden")


def test_load_model_returns_none_for_expected_model_load_errors(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "_MODEL_CACHE", None)
    monkeypatch.setattr(pipeline, "NLP_TIER2_MODEL_PATH", "tier2-model")
    monkeypatch.setitem(
        sys.modules,
        "spacy",
        SimpleNamespace(load=lambda _path: (_ for _ in ()).throw(OSError("model missing"))),
    )

    with patch("app.nlp.tier2_spacy.pipeline.logger.exception") as mock_log:
        result = pipeline._load_model()

    assert result is None
    mock_log.assert_called_once()


def test_load_model_surfaces_unexpected_model_load_errors(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "_MODEL_CACHE", None)
    monkeypatch.setattr(pipeline, "NLP_TIER2_MODEL_PATH", "tier2-model")
    monkeypatch.setitem(
        sys.modules,
        "spacy",
        SimpleNamespace(load=lambda _path: (_ for _ in ()).throw(AssertionError("unexpected model bug"))),
    )

    with patch("app.nlp.tier2_spacy.pipeline.logger.exception") as mock_log:
        with pytest.raises(AssertionError, match="unexpected model bug"):
            pipeline._load_model()

    mock_log.assert_not_called()

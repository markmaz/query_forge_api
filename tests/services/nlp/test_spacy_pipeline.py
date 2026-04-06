from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import sys

import pytest

import app.nlp.spacy_pipeline as spacy_pipeline


def test_get_nlp_returns_none_for_expected_model_load_errors(monkeypatch) -> None:
    spacy_pipeline._reset_nlp_cache_for_tests()
    monkeypatch.setattr(spacy_pipeline, "SPACY_MODEL_PATH", "fake-model")
    monkeypatch.setattr(spacy_pipeline, "GAZETTEER_ENABLED", False)
    monkeypatch.setitem(
        sys.modules,
        "spacy",
        SimpleNamespace(load=lambda _path: (_ for _ in ()).throw(OSError("model missing"))),
    )

    with patch("app.nlp.spacy_pipeline.logger.exception") as mock_log:
        result = spacy_pipeline.get_nlp()

    assert result is None
    mock_log.assert_called_once()
    spacy_pipeline._reset_nlp_cache_for_tests()


def test_get_nlp_surfaces_unexpected_model_load_errors(monkeypatch) -> None:
    spacy_pipeline._reset_nlp_cache_for_tests()
    monkeypatch.setattr(spacy_pipeline, "SPACY_MODEL_PATH", "fake-model")
    monkeypatch.setattr(spacy_pipeline, "GAZETTEER_ENABLED", False)
    monkeypatch.setitem(
        sys.modules,
        "spacy",
        SimpleNamespace(load=lambda _path: (_ for _ in ()).throw(AssertionError("unexpected loader bug"))),
    )

    with patch("app.nlp.spacy_pipeline.logger.exception") as mock_log:
        with pytest.raises(AssertionError, match="unexpected loader bug"):
            spacy_pipeline.get_nlp()

    mock_log.assert_not_called()
    spacy_pipeline._reset_nlp_cache_for_tests()

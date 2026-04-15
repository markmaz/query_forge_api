from __future__ import annotations

import builtins
from pathlib import Path
from unittest.mock import patch

import pytest

import app.nlp.tier2_spacy.training.dataset as dataset


def test_load_jsonl_wraps_expected_parse_errors(tmp_path: Path) -> None:
    src = tmp_path / "dataset.jsonl"
    src.write_text('{"text": "", "entities": []}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSONL at line 1"):
        dataset.load_jsonl(str(src))


def test_load_jsonl_surfaces_unexpected_parse_errors(tmp_path: Path) -> None:
    src = tmp_path / "dataset.jsonl"
    src.write_text('{"text": "valid"}\n', encoding="utf-8")

    with patch("app.nlp.tier2_spacy.training.dataset.parse_jsonl_line", side_effect=AssertionError("unexpected parse bug")):
        with pytest.raises(AssertionError, match="unexpected parse bug"):
            dataset.load_jsonl(str(src))


def test_to_docbin_wraps_missing_spacy_dependency(tmp_path: Path) -> None:
    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "spacy" or name.startswith("spacy"):
            raise ImportError("missing spaCy")
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=_fake_import):
        with pytest.raises(RuntimeError, match="spaCy is required to create DocBin"):
            dataset.to_docbin(
                jsonl_path=str(tmp_path / "missing.jsonl"),
                output_path=str(tmp_path / "out.spacy"),
            )


def test_to_docbin_surfaces_unexpected_spacy_import_errors(tmp_path: Path) -> None:
    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "spacy" or name.startswith("spacy"):
            raise AssertionError("unexpected import bug")
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=_fake_import):
        with pytest.raises(AssertionError, match="unexpected import bug"):
            dataset.to_docbin(
                jsonl_path=str(tmp_path / "missing.jsonl"),
                output_path=str(tmp_path / "out.spacy"),
            )

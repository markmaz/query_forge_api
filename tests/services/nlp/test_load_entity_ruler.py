from __future__ import annotations

from pathlib import Path

import pytest

from app.nlp.gazetteers.load_entity_ruler import add_school_district_ruler


def test_add_school_district_ruler_ignores_expected_overwrite_ents_errors(tmp_path: Path) -> None:
    patterns_path = tmp_path / "patterns.jsonl"
    patterns_path.write_text('{"label":"ORG_SCHOOL","pattern":[{"LOWER":"holden"}],"id":"Holden"}\n', encoding="utf-8")

    class _FakeRuler:
        def add_patterns(self, patterns):
            self.patterns = list(patterns)

    class _CompatNer:
        def __init__(self):
            self.cfg = {}

        @property
        def overwrite_ents(self):
            return True

        @overwrite_ents.setter
        def overwrite_ents(self, value):
            raise ValueError("compat setter failure")

    class _FakeNlp:
        pipe_names = ["ner"]

        def __init__(self):
            self._pipes = {"ner": _CompatNer(), "entity_ruler": _FakeRuler()}

        def get_pipe(self, name):
            return self._pipes[name]

        def add_pipe(self, name, before=None, config=None):
            return self._pipes["entity_ruler"]

    nlp = _FakeNlp()
    result = add_school_district_ruler(nlp, patterns_path)

    assert result is nlp
    assert nlp.get_pipe("entity_ruler").patterns[0]["id"] == "Holden"
    assert nlp.get_pipe("ner").cfg["overwrite_ents"] is False


def test_add_school_district_ruler_surfaces_unexpected_overwrite_ents_errors(tmp_path: Path) -> None:
    patterns_path = tmp_path / "patterns.jsonl"
    patterns_path.write_text('{"label":"ORG_SCHOOL","pattern":[{"LOWER":"holden"}],"id":"Holden"}\n', encoding="utf-8")

    class _FakeRuler:
        def add_patterns(self, patterns):
            self.patterns = list(patterns)

    class _BrokenNer:
        def __init__(self):
            self.cfg = {}

        @property
        def overwrite_ents(self):
            return True

        @overwrite_ents.setter
        def overwrite_ents(self, value):
            raise AssertionError("unexpected setter bug")

    class _FakeNlp:
        pipe_names = ["ner"]

        def __init__(self):
            self._pipes = {"ner": _BrokenNer(), "entity_ruler": _FakeRuler()}

        def get_pipe(self, name):
            return self._pipes[name]

        def add_pipe(self, name, before=None, config=None):
            return self._pipes["entity_ruler"]

    with pytest.raises(AssertionError, match="unexpected setter bug"):
        add_school_district_ruler(_FakeNlp(), patterns_path)

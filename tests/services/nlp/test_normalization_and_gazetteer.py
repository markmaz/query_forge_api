from __future__ import annotations

from pathlib import Path

import pytest

from app.nlp.gazetteer import build_entity_ruler, load_school_district_patterns
from app.nlp.normalization import normalize_prompt


def test_normalize_prompt_collapses_whitespace_and_quotes() -> None:
    raw = "  \u201cHow   many\u201d   students \u2014 in  district \u2018A\u2019  "
    assert normalize_prompt(raw) == "\"How many\" students - in district 'A'"


def test_gazetteer_tags_known_school_and_district(tmp_path: Path) -> None:
    spacy = pytest.importorskip("spacy")
    csv_path = tmp_path / "school_districts.csv"
    csv_path.write_text(
        "name,type\nHolden Elementary,school\nDavidson County Schools,district\n",
        encoding="utf-8",
    )

    patterns = load_school_district_patterns(str(csv_path))
    nlp = spacy.blank("en")
    build_entity_ruler(nlp, patterns)

    doc = nlp("How many students are at holden elementary in davidson county schools?")
    labeled = {(ent.label_, ent.text.lower()) for ent in doc.ents}
    assert ("ORG_SCHOOL", "holden elementary") in labeled
    assert ("ORG_DISTRICT", "davidson county schools") in labeled


def test_build_entity_ruler_ignores_expected_overwrite_ents_errors() -> None:
    class _FakeRuler:
        def add_patterns(self, patterns):
            self.patterns = list(patterns)

    class _CompatNer:
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
    ruler = build_entity_ruler(nlp, [{"label": "ORG_SCHOOL", "pattern": [{"LOWER": "holden"}], "id": "Holden"}])

    assert isinstance(ruler, _FakeRuler)
    assert len(ruler.patterns) == 1


def test_build_entity_ruler_surfaces_unexpected_overwrite_ents_errors() -> None:
    class _FakeRuler:
        def add_patterns(self, patterns):
            self.patterns = list(patterns)

    class _BrokenNer:
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
        build_entity_ruler(
            _FakeNlp(),
            [{"label": "ORG_SCHOOL", "pattern": [{"LOWER": "holden"}], "id": "Holden"}],
        )

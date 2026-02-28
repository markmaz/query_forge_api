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

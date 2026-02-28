from __future__ import annotations

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

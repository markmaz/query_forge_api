from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import srsly

SPACY_OVERWRITE_ENTS_COMPAT_ERRORS = (AttributeError, TypeError, ValueError)


def add_school_district_ruler(nlp: Any, patterns_path: str | Path) -> Any:
    """Attach a school/district EntityRuler and load JSONL patterns.

    The ruler is inserted before `ner` when present so deterministic gazetteer
    entities are created first. This function is safe to call when `ner` is
    missing or when the patterns file is absent.
    """

    path = Path(patterns_path)
    if not path.exists():
        return nlp

    if "entity_ruler" in nlp.pipe_names:
        ruler = nlp.get_pipe("entity_ruler")
    else:
        if "ner" in nlp.pipe_names:
            ruler = nlp.add_pipe("entity_ruler", before="ner", config={"phrase_matcher_attr": "LOWER"})
        else:
            ruler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})

    patterns: List[Dict[str, Any]] = []
    for row in srsly.read_jsonl(path):
        if isinstance(row, dict) and row.get("label") and row.get("pattern"):
            patterns.append(row)
    if patterns:
        ruler.add_patterns(patterns)

    if "ner" in nlp.pipe_names:
        ner = nlp.get_pipe("ner")
        if hasattr(ner, "overwrite_ents"):
            try:
                ner.overwrite_ents = False
            except SPACY_OVERWRITE_ENTS_COMPAT_ERRORS:
                pass
        if hasattr(ner, "cfg") and isinstance(getattr(ner, "cfg"), dict):
            ner.cfg["overwrite_ents"] = False
    return nlp

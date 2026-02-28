from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.config import SPACY_MODEL_PATH
from app.nlp.normalization import normalize_prompt
from app.nlp.spacy_pipeline import get_nlp

logger = logging.getLogger(__name__)


def extract_entities(text: str) -> Dict[str, Any]:
    normalized_text = normalize_prompt(text)
    warnings: List[str] = []
    ents: List[Dict[str, Any]] = []
    by_label: Dict[str, List[str]] = {}

    if normalized_text == "":
        return {
            "normalized_text": "",
            "ents": [],
            "by_label": {},
            "model": {"path": SPACY_MODEL_PATH, "loaded": False},
            "warnings": ["empty_prompt"],
        }

    nlp = get_nlp()
    if nlp is None:
        warnings.append("spacy_model_unavailable")
        return {
            "normalized_text": normalized_text,
            "ents": [],
            "by_label": {},
            "model": {"path": SPACY_MODEL_PATH, "loaded": False},
            "warnings": warnings,
        }

    doc = nlp(normalized_text)
    for ent in list(getattr(doc, "ents", []) or []):
        label = str(getattr(ent, "label_", "") or "").strip()
        value = str(getattr(ent, "text", "") or "").strip()
        if label == "" or value == "":
            continue
        start = int(getattr(ent, "start_char", 0))
        end = int(getattr(ent, "end_char", 0))
        ents.append({"start": start, "end": end, "label": label, "text": value})
        bucket = by_label.setdefault(label, [])
        if value not in bucket:
            bucket.append(value)

    counts_by_label = {label: len(values) for label, values in by_label.items()}
    logger.debug("spaCy extraction summary counts_by_label=%s", counts_by_label)
    return {
        "normalized_text": normalized_text,
        "ents": ents,
        "by_label": by_label,
        "model": {"path": SPACY_MODEL_PATH, "loaded": True},
        "warnings": warnings,
    }

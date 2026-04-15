from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import NLP_TIER2_ENABLED, NLP_TIER2_MODEL_PATH
from app.nlp.gazetteers import add_school_district_ruler
from app.nlp.tier2_spacy.router import route_topics
from app.nlp.tier2_spacy.schema import Tier2Entities, Tier2Extraction, empty_extraction
from app.nlp.tier2_spacy.slot_assigner import assign_slots

logger = logging.getLogger(__name__)
TIER2_INFERENCE_ERRORS = (OSError, RuntimeError, TypeError, ValueError)
TIER2_MODEL_LOAD_ERRORS = (ImportError, OSError, ValueError)


@dataclass
class _LoadedModel:
    nlp: Any
    model_version: str


_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: Optional[_LoadedModel] = None
_GAZETTEER_PATTERNS_PATH = Path(__file__).resolve().parents[1] / "gazetteers" / "school_districts_patterns.jsonl"


def run_tier2(prompt: str) -> Tier2Extraction:
    text = str(prompt or "").strip()
    if text == "":
        return empty_extraction(text, warnings=["empty_prompt"])

    if not NLP_TIER2_ENABLED:
        return empty_extraction(text, warnings=["tier2_disabled"])

    loaded = _load_model()
    warnings = []
    doc_entities = []
    cats: Dict[str, float] = {}
    if loaded is None:
        warnings.append("tier2_model_unavailable")
    else:
        try:
            doc = loaded.nlp(text)
            doc_entities = [
                {
                    "label": getattr(ent, "label_", ""),
                    "text": getattr(ent, "text", ""),
                    "score": 0.8,
                    "start": getattr(ent, "start_char", None),
                    "end": getattr(ent, "end_char", None),
                }
                for ent in list(getattr(doc, "ents", []) or [])
            ]
            cats = {
                str(key): float(value)
                for key, value in dict(getattr(doc, "cats", {}) or {}).items()
            }
        except TIER2_INFERENCE_ERRORS:
            logger.exception("Tier2 spaCy inference failed")
            warnings.append("tier2_inference_error")

    topic_payload = route_topics(text)
    slots, operators, intent_payload, slot_warnings = assign_slots(
        prompt=text,
        doc_entities=doc_entities,
        topic_scores=topic_payload.get("topic_scores", {}),
    )
    warnings.extend(slot_warnings)

    subject_hint = str(topic_payload.get("subject_entity_hint") or "unknown")
    confidence = 0.0 if subject_hint == "unknown" else 0.75
    if loaded is not None and doc_entities:
        confidence = min(0.95, max(confidence, 0.82))

    intent_scores = dict(intent_payload.get("scores", {}))
    for key, value in cats.items():
        intent_scores[key] = max(float(value), float(intent_scores.get(key, 0.0)))

    intent_label = str(intent_payload.get("label") or "")
    if not intent_label and intent_scores:
        intent_label = max(intent_scores.items(), key=lambda item: item[1])[0]

    extraction = Tier2Extraction(
        prompt=text,
        entities=Tier2Entities(subject_entity=subject_hint if subject_hint else "unknown", confidence=round(confidence, 4)),
        topic=list(topic_payload.get("topic") or []),
        slots=slots,
        operators=operators,
        intent={"label": intent_label or None, "scores": intent_scores},
        warnings=warnings,
    )
    return extraction


def run_tier2_with_meta(prompt: str) -> Dict[str, Any]:
    start = time.perf_counter()
    extraction = run_tier2(prompt)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    loaded = _MODEL_CACHE
    return {
        "plan_ir": extraction.model_dump(mode="json"),
        "model": {
            "enabled": bool(NLP_TIER2_ENABLED),
            "path": NLP_TIER2_MODEL_PATH,
            "version": loaded.model_version if loaded is not None else "unloaded",
        },
        "timings_ms": {"tier2": elapsed_ms},
    }


def _load_model() -> Optional[_LoadedModel]:
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE

    with _MODEL_LOCK:
        if _MODEL_CACHE is not None:
            return _MODEL_CACHE
        model_path = str(NLP_TIER2_MODEL_PATH or "").strip()
        if model_path == "":
            logger.info("Tier2 model path is empty; Tier2 will run heuristic-only")
            return None

        try:
            import spacy

            nlp = spacy.load(model_path)
            # Deterministic org tagging for known school/district names.
            add_school_district_ruler(nlp, _GAZETTEER_PATTERNS_PATH)
            _MODEL_CACHE = _LoadedModel(nlp=nlp, model_version=model_path)
            return _MODEL_CACHE
        except TIER2_MODEL_LOAD_ERRORS:
            logger.exception("Failed to load Tier2 spaCy model path=%s", model_path)
            return None

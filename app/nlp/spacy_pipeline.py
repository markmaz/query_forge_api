from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from app.config import GAZETTEER_CSV_PATH, GAZETTEER_ENABLED, SPACY_MODEL_PATH
from app.nlp.gazetteer import build_entity_ruler, load_school_district_patterns

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_NLP_CACHE: Optional[Any] = None
SPACY_MODEL_LOAD_ERRORS = (ImportError, OSError, ValueError)


def get_nlp() -> Optional[Any]:
    global _NLP_CACHE
    if _NLP_CACHE is not None:
        return _NLP_CACHE

    with _LOCK:
        if _NLP_CACHE is not None:
            return _NLP_CACHE
        model_path = str(SPACY_MODEL_PATH or "").strip()
        if model_path == "":
            logger.warning("spaCy model path is empty; planner extraction will run without NLP model")
            return None
        try:
            import spacy

            nlp = spacy.load(model_path)
            logger.info("Loaded spaCy pipeline from model path=%s", model_path)
        except SPACY_MODEL_LOAD_ERRORS:
            logger.exception("Failed to load spaCy model path=%s", model_path)
            return None

        if GAZETTEER_ENABLED:
            patterns = load_school_district_patterns(GAZETTEER_CSV_PATH)
            if patterns:
                build_entity_ruler(nlp, patterns)
                logger.info(
                    "Gazetteer enabled; loaded %d school/district patterns from %s",
                    len(patterns),
                    GAZETTEER_CSV_PATH,
                )
            else:
                logger.warning(
                    "Gazetteer enabled but no patterns were loaded from %s",
                    GAZETTEER_CSV_PATH,
                )
        else:
            logger.info("Gazetteer disabled")

        _NLP_CACHE = nlp
        return _NLP_CACHE


def _reset_nlp_cache_for_tests() -> None:
    global _NLP_CACHE
    with _LOCK:
        _NLP_CACHE = None

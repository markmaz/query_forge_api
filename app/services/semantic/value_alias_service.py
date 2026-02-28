from __future__ import annotations

import re
from typing import Dict, Optional

_TRAILING_ROLE_TOKENS = {"students", "student", "kids"}
_SUFFIX_STRIP_CONCEPTS = {"RACE", "ETHNICITY", "GENDER"}

_GENERIC_ALIASES: Dict[str, Dict[str, str]] = {
    "RACE": {
        "black": "Black - African American",
        "african american": "Black - African American",
        "african-american": "Black - African American",
        "african american students": "Black - African American",
    }
}


def canonicalize_value(concept_key: str, raw_value: str, vertical: str = "generic") -> Optional[str]:
    key = str(concept_key or "").strip().upper()
    if key == "":
        return None

    normalized = _normalize_value(key, raw_value)
    if normalized == "":
        return None

    vertical_key = str(vertical or "generic").strip().lower() or "generic"
    vertical_aliases = _aliases_for_vertical(vertical_key)
    concept_aliases = vertical_aliases.get(key) or {}
    if normalized in concept_aliases:
        return concept_aliases[normalized]
    return None


def _aliases_for_vertical(vertical: str) -> Dict[str, Dict[str, str]]:
    # Vertical-specific maps can be layered here later. For now generic is canonical.
    if vertical in {"generic", "education"}:
        return _GENERIC_ALIASES
    return _GENERIC_ALIASES


def _normalize_value(concept_key: str, raw_value: str) -> str:
    text = str(raw_value or "").strip().lower()
    if text == "":
        return ""
    text = text.replace("-", " ")
    text = re.sub(r"[^\w\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if concept_key in _SUFFIX_STRIP_CONCEPTS:
        tokens = [token for token in text.split() if token]
        while tokens and tokens[-1] in _TRAILING_ROLE_TOKENS:
            tokens.pop()
        text = " ".join(tokens).strip()
    return text


__all__ = ["canonicalize_value"]

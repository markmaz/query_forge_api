from __future__ import annotations

from app.services.ai_suggest.utils import (
    _QUOTED_LITERAL_RE,
    _YEAR_LITERAL_RE,
    _NUMBER_LITERAL_RE,
    _BOOLEAN_LITERAL_RE,
    _LABEL_VALUE_LITERAL_RE,
)


def prompt_contains_literal(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.strip()
    if not text:
        return False
    if ":" in text:
        return True
    if _QUOTED_LITERAL_RE.search(text):
        return True
    if _YEAR_LITERAL_RE.search(text):
        return True
    if _NUMBER_LITERAL_RE.search(text):
        return True
    if _BOOLEAN_LITERAL_RE.search(text):
        return True
    if _LABEL_VALUE_LITERAL_RE.search(text):
        return True
    return False


def prompt_implies_aggregation(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    for token in ("how many", "count", "total", "number of", "sum", "average", "avg"):
        if token in text:
            return True
    return False


def prompt_requests_distinct_count(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    tokens = ("distinct", "unique", "deduplicated", "deduped", "non-duplicate", "without duplicates")
    return any(token in text for token in tokens)


def prompt_implies_grouping(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = f" {prompt.lower()} "
    tokens = (
        " by ",
        " per ",
        " grouped by ",
        " for each ",
        " count by ",
        " sum by ",
        " average by ",
        " breakdown by ",
        " distribution by ",
    )
    return any(token in text for token in tokens)


def prompt_implies_sorting(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    tokens = (
        "sorted by",
        "order by",
        "top",
        "highest",
        "lowest",
        "most",
        "least",
        "rank",
        "descending",
        "ascending",
    )
    return any(token in text for token in tokens)


def prompt_implies_entity_listing(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    intent_tokens = ("show", "list", "display", "all", "give me")
    entity_tokens = ("student", "students", "school", "schools", "course", "courses")
    return any(token in text for token in intent_tokens) and any(token in text for token in entity_tokens)

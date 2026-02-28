from __future__ import annotations

import re

_RE_WHITESPACE = re.compile(r"\s+")

_UNICODE_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)


def normalize_prompt(text: str) -> str:
    value = str(text or "")
    normalized = value.translate(_UNICODE_TRANSLATION).strip()
    if normalized == "":
        return ""
    return _RE_WHITESPACE.sub(" ", normalized)

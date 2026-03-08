from __future__ import annotations

from urllib.parse import quote


class SigmaEmbedParams:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def add_param(self, key: str, value: str, encode: bool = False) -> "SigmaEmbedParams":
        rendered_value = quote(value, safe="") if encode else value
        self._parts.append(f":{key}={rendered_value}")
        return self

    @property
    def params(self) -> list[str]:
        return self._parts

    def __str__(self) -> str:
        if not self._parts:
            return ""
        return f"?{'&'.join(self._parts)}"

    def get_query_string(self) -> str:
        return str(self)

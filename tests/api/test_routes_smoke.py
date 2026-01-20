from __future__ import annotations

import re

_SKIP_PREFIXES = ("/swagger", "/docs", "/health", "/metrics")
_SKIP_SUBSTRINGS = ("purge",)
_CONVERTER_PLACEHOLDERS = {
    "int": "1",
    "integer": "1",
    "float": "1.0",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "path": "test-path",
    "string": "test",
    "unicode": "test",
    "any": "test",
}


def _build_url(path: str) -> str | None:
    def _replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if ":" in token:
            conv, _name = token.split(":", 1)
        else:
            conv = "string"
        conv = conv.split("(", 1)[0]
        return _CONVERTER_PLACEHOLDERS.get(conv, "test")

    replaced = re.sub(r"<([^>]+)>", _replace, path)
    if "<" in replaced or ">" in replaced:
        return None
    return replaced


def test_routes_smoke(client, app, auth_headers) -> None:
    failures: list[str] = []

    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.rule.startswith("/static"):
            continue
        if rule.rule.startswith(_SKIP_PREFIXES):
            continue
        if any(tag in rule.rule for tag in _SKIP_SUBSTRINGS):
            continue

        url = _build_url(rule.rule)
        if not url:
            continue

        methods = set(rule.methods or [])
        for method in ("GET", "POST"):
            if method not in methods:
                continue
            if method == "POST":
                resp = client.post(url, json={}, headers=auth_headers)
            else:
                resp = client.get(url, headers=auth_headers)
            if resp.status_code == 500:
                failures.append(f"{method} {url}")

    assert not failures, "500 responses:\n" + "\n".join(failures)

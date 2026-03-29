from __future__ import annotations

from typing import Any

from app.services.shared_ai.context import PipelineContext


def evaluate_condition(*, condition: str | None, context: PipelineContext) -> bool:
    if condition is None:
        return True

    token = str(condition).strip()
    if token == "":
        return True

    invert = False
    if token.startswith("!"):
        invert = True
        token = token[1:].strip()

    source_name, _, key = token.partition(":")
    if key == "":
        value: Any = context.metadata.get(token)
    elif source_name == "metadata":
        value = context.metadata.get(key)
    elif source_name == "artifacts":
        value = context.artifacts.get(key)
    elif source_name == "debug":
        value = context.debug.get(key)
    elif source_name == "request":
        value = context.request.get(key)
    else:
        value = context.metadata.get(token)

    result = bool(value)
    return (not result) if invert else result

from __future__ import annotations

from typing import Dict, Iterable

from app.services.shared_ai.graph import PipelineDefinition


class PipelineRegistry:
    def __init__(self) -> None:
        self._definitions: Dict[str, PipelineDefinition] = {}

    def register(self, definition: PipelineDefinition) -> None:
        self._definitions[definition.name] = definition

    def get(self, name: str) -> PipelineDefinition:
        return self._definitions[str(name)]

    def list_names(self) -> list[str]:
        return sorted(self._definitions.keys())

    def definitions(self) -> Iterable[PipelineDefinition]:
        return self._definitions.values()

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Type, TypeVar

from app.services.shared_ai.errors import MissingArtifactError

T = TypeVar("T")


@dataclass
class PipelineContext:
    pipeline_name: str
    trace_id: str
    workspace_id: Optional[str]
    user_id: Optional[str]
    request: dict[str, Any]
    artifacts: dict[str, Any] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_nodes: list[dict[str, Any]] = field(default_factory=list)

    def set_artifact(self, key: str, value: Any) -> None:
        self.artifacts[str(key)] = value

    def get_artifact(self, key: str, *, node_name: str = "unknown") -> Any:
        if key not in self.artifacts:
            raise MissingArtifactError(node_name=node_name, artifact_key=key)
        return self.artifacts[key]

    def get_optional_artifact(self, key: str, *, expected_type: Optional[Type[T]] = None) -> Optional[T]:
        value = self.artifacts.get(key)
        if value is None:
            return None
        if expected_type is not None and not isinstance(value, expected_type):
            return None
        return value

    def add_debug(self, key: str, value: Any) -> None:
        self.debug[str(key)] = value

    def add_trace_node(self, entry: dict[str, Any]) -> None:
        self.trace_nodes.append(dict(entry))

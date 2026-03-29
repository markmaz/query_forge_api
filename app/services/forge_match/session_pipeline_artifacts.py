from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ForgeMatchSessionWorkArtifact:
    session: dict[str, Any]
    source_rows: list[dict[str, Any]] = field(default_factory=list)
    existing_by_source: dict[int, str] = field(default_factory=dict)
    source_total: int = 0


@dataclass(frozen=True)
class ForgeMatchSessionExecutionArtifact:
    status: str
    analyzed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    last_source_row_id: str | None = None
    current_phase: str | None = None


@dataclass(frozen=True)
class ForgeMatchSessionResultArtifact:
    payload: dict[str, Any] = field(default_factory=dict)

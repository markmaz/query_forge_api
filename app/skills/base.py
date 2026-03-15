from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class QueryMetadata:
    """Metadata about the query that was run for this skill execution."""
    query_id: Any
    query_name: str
    column_names: List[str]
    column_types: Dict[str, str]
    row_count: int
    execution_time_ms: int
    executed_at: datetime


@dataclass
class SkillContext:
    workspace_id: str
    skill_id: str = ""
    execution_id: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    frontend_base_url: str = "http://localhost:3000"
    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    # Extended fields used by threshold_alert and tests
    query_id: Any = None
    triggered_by: Optional[str] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Optional[QueryMetadata] = None


class BaseSkill:
    skill_type: str = ""

    def execute(self, context: SkillContext) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.__class__.__name__}.execute() is not implemented")

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SkillContext:
    workspace_id: str
    skill_id: str
    execution_id: str
    config: Dict[str, Any] = field(default_factory=dict)
    frontend_base_url: str = "http://localhost:3000"
    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)


class BaseSkill:
    skill_type: str = ""

    def execute(self, context: SkillContext) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.__class__.__name__}.execute() is not implemented")

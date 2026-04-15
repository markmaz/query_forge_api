from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShareContext:
    workspace_id: str
    user_id: str

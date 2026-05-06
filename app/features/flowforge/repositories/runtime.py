from __future__ import annotations

from typing import Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.features.flowforge.repositories.runtime_assignments import FlowForgeRuntimeAssignmentRepositoryMixin
from app.features.flowforge.repositories.runtime_events import FlowForgeRuntimeEventRepositoryMixin
from app.features.flowforge.repositories.runtime_human_tasks import FlowForgeRuntimeHumanTaskRepositoryMixin
from app.features.flowforge.repositories.runtime_matching import FlowForgeRuntimeMatchingRepositoryMixin
from app.features.flowforge.repositories.runtime_notifications import FlowForgeRuntimeNotificationRepositoryMixin
from app.features.flowforge.repositories.runtime_runs import FlowForgeRuntimeRunRepositoryMixin
from app.features.flowforge.repositories.runtime_signed_actions import FlowForgeRuntimeSignedActionRepositoryMixin
from app.ports.sql_executor import ForgeQueryPort


class FlowForgeRuntimeRepository(
    FlowForgeRuntimeRunRepositoryMixin,
    FlowForgeRuntimeEventRepositoryMixin,
    FlowForgeRuntimeHumanTaskRepositoryMixin,
    FlowForgeRuntimeMatchingRepositoryMixin,
    FlowForgeRuntimeAssignmentRepositoryMixin,
    FlowForgeRuntimeSignedActionRepositoryMixin,
    FlowForgeRuntimeNotificationRepositoryMixin,
):
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

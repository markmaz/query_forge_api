from __future__ import annotations

from typing import Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.features.flowforge.repositories.data_movement_allowlists import FlowForgeDataMovementAllowlistRepositoryMixin
from app.features.flowforge.repositories.data_movement_artifacts import FlowForgeDataMovementArtifactRepositoryMixin
from app.features.flowforge.repositories.data_movement_audit import FlowForgeDataMovementAuditRepositoryMixin
from app.features.flowforge.repositories.data_movement_decoders import FlowForgeDataMovementDecoderMixin
from app.features.flowforge.repositories.data_movement_operations import FlowForgeDataMovementOperationsRepositoryMixin
from app.features.flowforge.repositories.data_movement_schedule import FlowForgeDataMovementScheduleRepositoryMixin
from app.ports.sql_executor import ForgeQueryPort


class FlowForgeDataMovementRepository(
    FlowForgeDataMovementArtifactRepositoryMixin,
    FlowForgeDataMovementAuditRepositoryMixin,
    FlowForgeDataMovementAllowlistRepositoryMixin,
    FlowForgeDataMovementScheduleRepositoryMixin,
    FlowForgeDataMovementOperationsRepositoryMixin,
    FlowForgeDataMovementDecoderMixin,
):
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

from __future__ import annotations


class FlowForgeDataMovementOperationsRepositoryMixin:
    def expire_dataset_artifacts(self, *, limit: int = 500) -> int:
        capped_limit = max(1, min(int(limit or 500), 5000))
        return int(
            self._sql.execute_write(
                """
                UPDATE flowforge_dataset_artifacts
                SET status = 'expired',
                    updated_at = CURRENT_TIMESTAMP
                WHERE expires_at IS NOT NULL
                  AND expires_at <= CURRENT_TIMESTAMP
                  AND status NOT IN ('expired', 'deleted')
                ORDER BY expires_at ASC, id ASC
                LIMIT :limit
                """,
                {"limit": capped_limit},
            )
            or 0
        )

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor


class SemanticAssignmentService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def upsert_primary_semantics(
        self,
        *,
        model_column_id: int,
        semantic_concept_id: Optional[int],
        key: Optional[str],
        source: Optional[str],
        confidence: Optional[float],
        reasons: Optional[List[str]],
        warnings: Optional[List[str]],
        entity: Optional[str],
        sub_type: Optional[str],
        granularity_rank: int,
    ) -> int:
        return self._sql.execute_write(
            """
            UPDATE model_column
            SET semantic_concept_id = :semantic_concept_id,
                semantic_concept_key = :semantic_concept_key,
                semantic_entity = :semantic_entity,
                semantic_sub_type = :semantic_sub_type,
                semantic_granularity_rank = :semantic_granularity_rank,
                semantic_source = :semantic_source,
                semantic_confidence = :semantic_confidence,
                semantic_reasons_json = :semantic_reasons_json,
                semantic_warnings_json = :semantic_warnings_json,
                semantic_updated_at = CURRENT_TIMESTAMP
            WHERE id = :model_column_id
            """,
            {
                "model_column_id": int(model_column_id),
                "semantic_concept_id": int(semantic_concept_id) if semantic_concept_id is not None else None,
                "semantic_concept_key": (str(key).strip() if key is not None else None),
                "semantic_entity": (str(entity).strip() if entity is not None else None),
                "semantic_sub_type": (str(sub_type).strip() if sub_type is not None else None),
                "semantic_granularity_rank": int(granularity_rank),
                "semantic_source": (str(source).strip().lower() if source is not None else None),
                "semantic_confidence": float(confidence) if confidence is not None else None,
                "semantic_reasons_json": json.dumps(reasons or []),
                "semantic_warnings_json": json.dumps(warnings or []),
            },
        )

    def ensure_mapping(
        self,
        *,
        model_column_id: int,
        semantic_concept_id: int,
        relationship_kind: str = "primary",
        weight: float = 1.0,
        vertical_norm: str = "generic",
    ) -> int:
        return self._sql.execute_write(
            """
            INSERT INTO model_column_semantic_concept_map (
              vertical_norm,
              semantic_concept_id,
              model_column_id,
              relationship_kind,
              weight
            ) VALUES (
              :vertical_norm,
              :semantic_concept_id,
              :model_column_id,
              :relationship_kind,
              :weight
            )
            ON DUPLICATE KEY UPDATE
              weight = GREATEST(weight, VALUES(weight))
            """,
            {
                "vertical_norm": (str(vertical_norm or "generic").strip().lower() or "generic"),
                "semantic_concept_id": int(semantic_concept_id),
                "model_column_id": int(model_column_id),
                "relationship_kind": (str(relationship_kind or "primary").strip().lower() or "primary"),
                "weight": float(weight),
            },
        )


__all__ = ["SemanticAssignmentService"]

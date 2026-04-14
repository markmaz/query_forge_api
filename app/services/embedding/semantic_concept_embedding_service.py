from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional

from qdrant_client.http import models as qdrant_models

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QDRANT_SEMANTIC_CONCEPT_COLLECTION
from app.infra.embedding_model import DEFAULT_VECTOR_SIZE, EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.ports.sql_executor import ForgeQueryPort

COLLECTION_NAME = QDRANT_SEMANTIC_CONCEPT_COLLECTION or "semantic_concepts_v1"
VECTOR_SIZE = DEFAULT_VECTOR_SIZE


class SemanticConceptEmbeddingService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        qdrant: Optional[QdrantClientWrapper] = None,
        model: Optional[EmbeddingModel] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._qdrant = qdrant or QdrantClientWrapper(collection_name=COLLECTION_NAME)
        self._model = model or EmbeddingModel()

    def rebuild_semantic_concept_index(self) -> Dict[str, int]:
        self._qdrant.ensure_collection(COLLECTION_NAME, VECTOR_SIZE)

        concept_rows = self._load_concepts()
        alias_rows = self._load_aliases()

        concept_count = self._upsert_concepts(concept_rows)
        alias_count = self._upsert_aliases(alias_rows)

        return {
            "conceptPoints": concept_count,
            "aliasPoints": alias_count,
        }

    def upsert_concept_point(self, concept_id: int) -> int:
        self._qdrant.ensure_collection(COLLECTION_NAME, VECTOR_SIZE)
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              concept_key,
              name,
              description,
              semantic_type,
              sub_type,
              entity,
              filter_allowed,
              group_by_allowed,
              aggregation_allowed,
              is_identifier,
              is_metric
            FROM semantic_concept
            WHERE id = :id
              AND `status` = 'active'
            LIMIT 1
            """,
            {"id": int(concept_id)},
        )
        if not rows:
            return 0
        return self._upsert_concepts(rows)

    def upsert_alias_point(self, alias_id: int) -> int:
        self._qdrant.ensure_collection(COLLECTION_NAME, VECTOR_SIZE)
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              a.id AS alias_id,
              a.alias_key,
              a.concept_key,
              a.match_kind,
              a.weight,
              c.id AS concept_id,
              c.name AS concept_name,
              c.description AS concept_description
            FROM semantic_concept_alias a
            LEFT JOIN semantic_concept c
              ON c.concept_key = a.concept_key
             AND c.`status` = 'active'
            WHERE a.id = :id
            LIMIT 1
            """,
            {"id": int(alias_id)},
        )
        if not rows:
            return 0
        return self._upsert_aliases(rows)

    def _load_concepts(self) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT
              id,
              concept_key,
              name,
              description,
              semantic_type,
              sub_type,
              entity,
              filter_allowed,
              group_by_allowed,
              aggregation_allowed,
              is_identifier,
              is_metric
            FROM semantic_concept
            WHERE `status` = 'active'
            ORDER BY concept_key
            """,
            None,
        )

    def _load_aliases(self) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT
              a.id AS alias_id,
              a.alias_key,
              a.concept_key,
              a.match_kind,
              a.weight,
              c.id AS concept_id,
              c.name AS concept_name,
              c.description AS concept_description
            FROM semantic_concept_alias a
            LEFT JOIN semantic_concept c
              ON c.concept_key = a.concept_key
             AND c.`status` = 'active'
            ORDER BY a.id
            """,
            None,
        )

    def _upsert_concepts(self, rows: Iterable[Dict[str, Any]]) -> int:
        row_list = list(rows)
        if not row_list:
            return 0
        texts = [self._concept_text(r) for r in row_list]
        vectors = self._model.encode(texts, normalize=True, batch_size=64)
        points: List[qdrant_models.PointStruct] = []
        for row, vector in zip(row_list, vectors, strict=True):
            concept_id = int(row["id"])
            payload = {
                "type": "concept",
                "concept_id": concept_id,
                "concept_key": row.get("concept_key"),
                "name": row.get("name"),
                "description": row.get("description"),
                "semantic_type": row.get("semantic_type"),
                "sub_type": row.get("sub_type"),
                "entity": row.get("entity"),
                "filter_allowed": int(bool(row.get("filter_allowed"))),
                "group_by_allowed": int(bool(row.get("group_by_allowed"))),
                "aggregation_allowed": int(bool(row.get("aggregation_allowed"))),
                "is_identifier": int(bool(row.get("is_identifier"))),
                "is_metric": int(bool(row.get("is_metric"))),
            }
            points.append(
                qdrant_models.PointStruct(
                    id=_point_id("concept", concept_id),
                    vector=vector,
                    payload=payload,
                )
            )
        return self._qdrant.upsert_points(points)

    def _upsert_aliases(self, rows: Iterable[Dict[str, Any]]) -> int:
        row_list = list(rows)
        if not row_list:
            return 0
        texts = [self._alias_text(r) for r in row_list]
        vectors = self._model.encode(texts, normalize=True, batch_size=64)
        points: List[qdrant_models.PointStruct] = []
        for row, vector in zip(row_list, vectors, strict=True):
            alias_id = int(row["alias_id"])
            payload = {
                "type": "alias",
                "alias_id": alias_id,
                "alias_key": row.get("alias_key"),
                "concept_id": row.get("concept_id"),
                "concept_key": row.get("concept_key"),
                "match_kind": row.get("match_kind"),
                "weight": float(row.get("weight") or 0.0),
            }
            points.append(
                qdrant_models.PointStruct(
                    id=_point_id("alias", alias_id),
                    vector=vector,
                    payload=payload,
                )
            )
        return self._qdrant.upsert_points(points)

    @staticmethod
    def _concept_text(row: Dict[str, Any]) -> str:
        concept_key = str(row.get("concept_key") or "").strip()
        name = str(row.get("name") or "").strip()
        semantic_type = str(row.get("semantic_type") or "").strip()
        sub_type = str(row.get("sub_type") or "").strip()
        entity = str(row.get("entity") or "").strip()
        description = str(row.get("description") or "").strip()
        return f"{concept_key} | {name} | {semantic_type} {sub_type} | entity={entity} | {description}"

    @staticmethod
    def _alias_text(row: Dict[str, Any]) -> str:
        alias_key = str(row.get("alias_key") or "").strip()
        concept_key = str(row.get("concept_key") or "").strip()
        concept_name = str(row.get("concept_name") or "").strip()
        concept_description = str(row.get("concept_description") or "").strip()
        return f"{alias_key} -> {concept_key} | {concept_name} | {concept_description}"


def _point_id(kind: str, row_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"semantic:{kind}:{int(row_id)}"))
__all__ = ["SemanticConceptEmbeddingService"]

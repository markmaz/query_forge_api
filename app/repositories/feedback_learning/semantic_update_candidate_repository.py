from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort

from app.repositories.feedback_learning._shared import parse_json_object, serialize_json_object


class SemanticUpdateCandidateRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_by_id(self, *, candidate_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM semantic_update_candidate
            WHERE id = :id
            LIMIT 1
            """,
            {"id": int(candidate_id)},
        )
        return _normalize_candidate_row(rows[0]) if rows else None

    def find_by_payload_scope(
        self,
        *,
        payload_hash: str,
        source_scope: str,
        workspace_scope_key: str,
    ) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM semantic_update_candidate
            WHERE payload_hash = :payload_hash
              AND source_scope = :source_scope
              AND workspace_scope_key = :workspace_scope_key
            LIMIT 1
            """,
            {
                "payload_hash": str(payload_hash or "").strip(),
                "source_scope": str(source_scope or "").strip(),
                "workspace_scope_key": str(workspace_scope_key or "").strip(),
            },
        )
        return _normalize_candidate_row(rows[0]) if rows else None

    def insert_candidate(self, *, payload: Dict[str, Any]) -> ForgeExecResult:
        params = dict(payload)
        params["payload_json"] = serialize_json_object(payload.get("payload_json") or payload.get("payload"))
        return self._sql.execute_insert(
            """
            INSERT INTO semantic_update_candidate (
              failure_analysis_id,
              target_type,
              concept_key,
              domain_key,
              change_type,
              payload_json,
              payload_hash,
              risk_level,
              evidence_count,
              confidence,
              governance_status,
              auto_apply_eligible,
              source_scope,
              workspace_id,
              workspace_scope_key,
              reviewed_by,
              reviewed_at
            ) VALUES (
              :failure_analysis_id,
              :target_type,
              :concept_key,
              :domain_key,
              :change_type,
              :payload_json,
              :payload_hash,
              :risk_level,
              :evidence_count,
              :confidence,
              :governance_status,
              :auto_apply_eligible,
              :source_scope,
              :workspace_id,
              :workspace_scope_key,
              :reviewed_by,
              :reviewed_at
            )
            """,
            params,
        )

    def update_evidence_and_confidence(
        self,
        *,
        candidate_id: int,
        evidence_count: int,
        confidence: float,
    ) -> int:
        return int(
            self._sql.execute_write(
                """
                UPDATE semantic_update_candidate
                SET evidence_count = :evidence_count,
                    confidence = :confidence,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                {
                    "id": int(candidate_id),
                    "evidence_count": int(evidence_count),
                    "confidence": float(confidence),
                },
            )
            or 0
        )

    def update_review(
        self,
        *,
        candidate_id: int,
        governance_status: str,
        reviewed_by: Optional[str] = None,
        reviewed_at: Optional[Any] = None,
        auto_apply_eligible: Optional[bool] = None,
        governance_reason_code: Optional[str] = None,
        review_notes: Optional[str] = None,
    ) -> int:
        return int(
            self._sql.execute_write(
                """
                UPDATE semantic_update_candidate
                SET governance_status = :governance_status,
                    reviewed_by = :reviewed_by,
                    reviewed_at = :reviewed_at,
                    auto_apply_eligible = COALESCE(:auto_apply_eligible, auto_apply_eligible),
                    governance_reason_code = :governance_reason_code,
                    review_notes = :review_notes,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                {
                    "id": int(candidate_id),
                    "governance_status": str(governance_status or "").strip(),
                    "reviewed_by": reviewed_by,
                    "reviewed_at": reviewed_at,
                    "auto_apply_eligible": auto_apply_eligible,
                    "governance_reason_code": str(governance_reason_code or "").strip() or None,
                    "review_notes": str(review_notes or "").strip() or None,
                },
            )
            or 0
        )

    def list_candidates(
        self,
        *,
        governance_status: Optional[str] = None,
        risk_level: Optional[str] = None,
        target_type: Optional[str] = None,
        workspace_id: Optional[str] = None,
        change_type: Optional[str] = None,
        concept_key: Optional[str] = None,
        domain_key: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        filters = []
        params: Dict[str, Any] = {}
        for key, value in (
            ("governance_status", governance_status),
            ("risk_level", risk_level),
            ("target_type", target_type),
            ("workspace_id", workspace_id),
            ("change_type", change_type),
            ("concept_key", concept_key),
            ("domain_key", domain_key),
        ):
            token = str(value or "").strip()
            if token == "":
                continue
            filters.append(f"{key} = :{key}")
            params[key] = token

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        page_value = max(1, int(page or 1))
        size_value = max(1, min(200, int(page_size or 50)))
        offset = (page_value - 1) * size_value
        params.update({"limit": size_value, "offset": offset})

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM semantic_update_candidate
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        count_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_update_candidate
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((count_rows[0] or {}).get("total") or 0) if count_rows else 0
        return {
            "rows": [_normalize_candidate_row(row) for row in rows],
            "total": total,
            "page": page_value,
            "page_size": size_value,
        }


def _normalize_candidate_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(raw)
    row["payload_json"] = parse_json_object(row.get("payload_json"))
    return row


__all__ = ["SemanticUpdateCandidateRepository"]

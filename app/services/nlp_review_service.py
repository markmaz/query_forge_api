from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


class NLPReviewService:
    VALID_STATUSES = {"pending", "approved", "rejected"}

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def enqueue(
        self,
        *,
        workspace_id: str,
        prompt: str,
        model_version: str,
        prediction_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip()
        text = str(prompt or "").strip()
        if ws == "":
            raise ForgeError("workspace_id is required", status_code=400)
        if text == "":
            raise ForgeError("prompt is required", status_code=400)

        insert = self._sql.execute_insert(
            """
            INSERT INTO nlp_review_item (
              workspace_id,
              prompt,
              model_version,
              prediction_json,
              status
            ) VALUES (
              :workspace_id,
              :prompt,
              :model_version,
              :prediction_json,
              'pending'
            )
            """,
            {
                "workspace_id": ws,
                "prompt": text,
                "model_version": str(model_version or "unknown"),
                "prediction_json": json.dumps(prediction_json or {}, ensure_ascii=True),
            },
        )
        row_id = int(insert.lastrowid or 0)
        return self.get_item(workspace_id=ws, item_id=row_id)

    def get_item(self, *, workspace_id: str, item_id: int) -> Dict[str, Any]:
        row = self._fetch_one(workspace_id=workspace_id, item_id=item_id)
        if row is None:
            raise ForgeError("review item not found", status_code=404)
        return row

    def list_items(
        self,
        *,
        workspace_id: str,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip()
        if ws == "":
            raise ForgeError("workspace_id is required", status_code=400)

        params: Dict[str, Any] = {"workspace_id": ws, "limit": max(1, min(500, int(limit or 50)))}
        where = ["workspace_id = :workspace_id"]
        status_norm = str(status or "").strip().lower()
        if status_norm:
            if status_norm not in self.VALID_STATUSES:
                raise ForgeError("invalid status", status_code=400)
            where.append("status = :status")
            params["status"] = status_norm

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              id,
              workspace_id,
              prompt,
              model_version,
              prediction_json,
              corrected_json,
              status,
              created_at,
              updated_at
            FROM nlp_review_item
            WHERE {' AND '.join(where)}
            ORDER BY id DESC
            LIMIT :limit
            """,
            params,
        )
        return {
            "rows": [self._deserialize_row(row) for row in rows],
            "count": len(rows),
        }

    def patch_item(
        self,
        *,
        workspace_id: str,
        item_id: int,
        status: Optional[str] = None,
        corrected: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip()
        if ws == "":
            raise ForgeError("workspace_id is required", status_code=400)

        updates: List[str] = []
        params: Dict[str, Any] = {"workspace_id": ws, "id": int(item_id)}

        if status is not None:
            status_norm = str(status).strip().lower()
            if status_norm not in self.VALID_STATUSES:
                raise ForgeError("invalid status", status_code=400)
            updates.append("status = :status")
            params["status"] = status_norm

        if corrected is not None:
            updates.append("corrected_json = :corrected_json")
            params["corrected_json"] = json.dumps(corrected, ensure_ascii=True)

        if not updates:
            return self.get_item(workspace_id=ws, item_id=item_id)

        rowcount = self._sql.execute_write(
            f"""
            UPDATE nlp_review_item
            SET {', '.join(updates)}
            WHERE id = :id AND workspace_id = :workspace_id
            """,
            params,
        )
        if rowcount <= 0:
            raise ForgeError("review item not found", status_code=404)
        return self.get_item(workspace_id=ws, item_id=item_id)

    def approve_item(self, *, workspace_id: str, item_id: int) -> Dict[str, Any]:
        return self.patch_item(workspace_id=workspace_id, item_id=item_id, status="approved")

    def export_item_jsonl(self, *, workspace_id: str, item_id: int) -> Dict[str, Any]:
        row = self.get_item(workspace_id=workspace_id, item_id=item_id)
        if str(row.get("status") or "").lower() != "approved":
            raise ForgeError("review item must be approved before export", status_code=400)

        corrected = row.get("corrected")
        if not isinstance(corrected, dict):
            raise ForgeError("review item has no corrected payload", status_code=400)

        line = {
            "text": row.get("prompt") or "",
            "entities": corrected.get("entities") or [],
            "cats": corrected.get("cats") or {},
            "meta": {
                "workspace_id": row.get("workspace_id"),
                "review_item_id": row.get("id"),
                "source": "nlp_review_queue",
            },
        }
        return {"jsonl": json.dumps(line, ensure_ascii=False), "line": line}

    def _fetch_one(self, *, workspace_id: str, item_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              workspace_id,
              prompt,
              model_version,
              prediction_json,
              corrected_json,
              status,
              created_at,
              updated_at
            FROM nlp_review_item
            WHERE id = :id AND workspace_id = :workspace_id
            LIMIT 1
            """,
            {"id": int(item_id), "workspace_id": str(workspace_id or "")},
        )
        if not rows:
            return None
        return self._deserialize_row(rows[0])

    @staticmethod
    def _deserialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        out["prediction"] = NLPReviewService._safe_json_load(out.pop("prediction_json", None))
        out["corrected"] = NLPReviewService._safe_json_load(out.pop("corrected_json", None))
        return out

    @staticmethod
    def _safe_json_load(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        text = str(value).strip()
        if text == "":
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

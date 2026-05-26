from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.domain_profile import (
    DomainProfileCreateRequest,
    DomainProfileResponse,
    DomainProfileUpdateRequest,
    compute_content_hash,
    _build_embedding_text,
)
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

_LIST_QUERY = """
SELECT
    dp.id,
    dp.workspace_id,
    dp.domain_id,
    dp.summary,
    dp.keywords,
    dp.entities,
    dp.metrics,
    dp.attributes,
    dp.synonyms,
    dp.acronyms,
    dp.notes,
    dp.embedding_text,
    dp.content_hash,
    dp.embedding_model,
    dp.embedded_at,
    dp.created_at,
    dp.updated_at,
    d.name AS domain_name,
    d.kind AS domain_kind
FROM domain_profile dp
LEFT JOIN domain d ON d.id = dp.domain_id
WHERE dp.workspace_id = :workspace_id
ORDER BY dp.domain_id
"""

_GET_QUERY = """
SELECT
    dp.id,
    dp.workspace_id,
    dp.domain_id,
    dp.summary,
    dp.keywords,
    dp.entities,
    dp.metrics,
    dp.attributes,
    dp.synonyms,
    dp.acronyms,
    dp.notes,
    dp.embedding_text,
    dp.content_hash,
    dp.embedding_model,
    dp.embedded_at,
    dp.created_at,
    dp.updated_at,
    d.name AS domain_name,
    d.kind AS domain_kind
FROM domain_profile dp
LEFT JOIN domain d ON d.id = dp.domain_id
WHERE dp.workspace_id = :workspace_id AND dp.domain_id = :domain_id
"""

_INSERT_QUERY = """
INSERT INTO domain_profile (
    workspace_id, domain_id, summary, keywords, entities,
    metrics, attributes, synonyms, acronyms, notes,
    embedding_text, content_hash
) VALUES (
    :workspace_id, :domain_id, :summary, :keywords, :entities,
    :metrics, :attributes, :synonyms, :acronyms, :notes,
    :embedding_text, :content_hash
)
"""

_UPDATE_QUERY = """
UPDATE domain_profile
SET summary = :summary,
    keywords = :keywords,
    entities = :entities,
    metrics = :metrics,
    attributes = :attributes,
    synonyms = :synonyms,
    acronyms = :acronyms,
    notes = :notes,
    embedding_text = :embedding_text,
    content_hash = :content_hash
WHERE workspace_id = :workspace_id AND domain_id = :domain_id
"""

_DELETE_QUERY = """
DELETE FROM domain_profile
WHERE workspace_id = :workspace_id AND domain_id = :domain_id
"""


class DomainProfileService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_profiles(self, workspace_id: str) -> List[Dict[str, Any]]:
        workspace = (workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)
        rows = self._sql.execute_query_mappings(_LIST_QUERY, {"workspace_id": workspace})
        return [_row_to_response(r).model_dump(mode="json") for r in rows]

    def get_profile(self, workspace_id: str, domain_id: int) -> Dict[str, Any]:
        workspace = (workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)
        rows = self._sql.execute_query_mappings(
            _GET_QUERY, {"workspace_id": workspace, "domain_id": domain_id}
        )
        if not rows:
            raise ForgeError(
                "Domain profile not found",
                status_code=404,
                details={"workspace_id": workspace, "domain_id": domain_id},
            )
        return _row_to_response(rows[0]).model_dump(mode="json")

    def create_profile(self, req: DomainProfileCreateRequest) -> Dict[str, Any]:
        existing = self._sql.execute_query_mappings(
            _GET_QUERY,
            {"workspace_id": req.workspace_id, "domain_id": req.domain_id},
        )
        if existing:
            raise ForgeError(
                "Domain profile already exists",
                status_code=409,
                details={"workspace_id": req.workspace_id, "domain_id": req.domain_id},
            )

        embedding_text = req.embedding_text or _build_embedding_text(req)
        content_hash = compute_content_hash(embedding_text)
        params = _request_to_params(req, embedding_text, content_hash)
        self._sql.execute_write(_INSERT_QUERY, params)
        return self.get_profile(req.workspace_id, req.domain_id)

    def update_profile(
        self, workspace_id: str, domain_id: int, req: DomainProfileUpdateRequest
    ) -> Dict[str, Any]:
        workspace = (workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)

        existing = self._sql.execute_query_mappings(
            _GET_QUERY, {"workspace_id": workspace, "domain_id": domain_id}
        )
        if not existing:
            raise ForgeError(
                "Domain profile not found",
                status_code=404,
                details={"workspace_id": workspace, "domain_id": domain_id},
            )

        merged = _merge_update(existing[0], req)
        embedding_text = merged.get("embedding_text") or ""
        content_hash = compute_content_hash(embedding_text)

        params = {
            "workspace_id": workspace,
            "domain_id": domain_id,
            "summary": merged.get("summary"),
            "keywords": _json_dumps(merged.get("keywords")),
            "entities": _json_dumps(merged.get("entities")),
            "metrics": _json_dumps(merged.get("metrics")),
            "attributes": _json_dumps(merged.get("attributes")),
            "synonyms": _json_dumps(merged.get("synonyms")),
            "acronyms": _json_dumps(merged.get("acronyms")),
            "notes": merged.get("notes"),
            "embedding_text": embedding_text,
            "content_hash": content_hash,
        }
        self._sql.execute_write(_UPDATE_QUERY, params)
        return self.get_profile(workspace, domain_id)

    def delete_profile(self, workspace_id: str, domain_id: int) -> Dict[str, Any]:
        workspace = (workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)

        existing = self._sql.execute_query_mappings(
            _GET_QUERY, {"workspace_id": workspace, "domain_id": domain_id}
        )
        if not existing:
            raise ForgeError(
                "Domain profile not found",
                status_code=404,
                details={"workspace_id": workspace, "domain_id": domain_id},
            )

        self._sql.execute_write(
            _DELETE_QUERY, {"workspace_id": workspace, "domain_id": domain_id}
        )
        return {"deleted": True, "workspace_id": workspace, "domain_id": domain_id}


def _row_to_response(row: Dict[str, Any]) -> DomainProfileResponse:
    return DomainProfileResponse(
        id=row["id"],
        workspace_id=row["workspace_id"],
        domain_id=row["domain_id"],
        summary=row.get("summary"),
        keywords=_parse_json(row.get("keywords")),
        entities=_parse_json(row.get("entities")),
        metrics=_parse_json(row.get("metrics")),
        attributes=_parse_json(row.get("attributes")),
        synonyms=_parse_json(row.get("synonyms")),
        acronyms=_parse_json(row.get("acronyms")),
        notes=row.get("notes"),
        embedding_text=row.get("embedding_text"),
        content_hash=row.get("content_hash"),
        embedding_model=row.get("embedding_model"),
        embedded_at=row.get("embedded_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        domain_name=row.get("domain_name"),
        domain_kind=row.get("domain_kind"),
    )


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _request_to_params(
    req: DomainProfileCreateRequest, embedding_text: str, content_hash: str
) -> Dict[str, Any]:
    return {
        "workspace_id": req.workspace_id,
        "domain_id": req.domain_id,
        "summary": req.summary,
        "keywords": _json_dumps(req.keywords),
        "entities": _json_dumps(req.entities),
        "metrics": _json_dumps(req.metrics),
        "attributes": _json_dumps(req.attributes),
        "synonyms": _json_dumps(req.synonyms),
        "acronyms": _json_dumps(req.acronyms),
        "notes": req.notes,
        "embedding_text": embedding_text,
        "content_hash": content_hash,
    }


def _merge_update(existing: Dict[str, Any], req: DomainProfileUpdateRequest) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for field in ("summary", "notes"):
        req_val = getattr(req, field, None)
        merged[field] = req_val if req_val is not None else existing.get(field)

    for field in ("keywords", "entities", "metrics", "attributes", "synonyms", "acronyms"):
        req_val = getattr(req, field, None)
        if req_val is not None:
            merged[field] = req_val
        else:
            merged[field] = _parse_json(existing.get(field))

    if req.embedding_text is not None:
        merged["embedding_text"] = req.embedding_text
    else:
        temp = DomainProfileUpdateRequest(**{k: v for k, v in merged.items() if k != "embedding_text"})
        merged["embedding_text"] = _build_embedding_text(temp)

    return merged

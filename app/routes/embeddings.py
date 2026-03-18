from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.services.embedding.domain_embedding_service import DomainEmbeddingService
from app.services.embedding.embedding_index_service import EmbeddingIndexService
from app.services.embedding.embedding_search_service import EmbeddingSearchService

logger = logging.getLogger(__name__)

embeddings_ns = Namespace("embeddings", description="Embedding indexing")


def _parse_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return default


def _parse_limit(value) -> int:
    try:
        limit = int(value)
    except Exception:
        return 0
    return max(0, limit)


def _parse_limit_cap(value, default: int = 10, cap: int = 50) -> int:
    try:
        limit = int(value)
    except Exception:
        limit = default
    if limit <= 0:
        limit = default
    return min(limit, cap)


def _parse_min_score(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        raise ForgeError("minScore must be a number", status_code=400)


def _parse_model_table_id(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        raise ForgeError("modelTableId must be an integer", status_code=400)


@embeddings_ns.route("/rebuild")
class EmbeddingsRebuild(ForgeResource):
    @token_required
    @require_access("vector", role="admin")
    def post(self):
        body = request.get_json(silent=True) or {}
        include_tables = _parse_bool(body.get("includeTables"), True)
        limit = _parse_limit(body.get("limit", 0))
        workspace_id = (body.get("workspace_id") or body.get("workspaceId") or "").strip() or None

        try:
            service = EmbeddingIndexService()
            result = service.rebuild_index(
                include_tables=include_tables,
                limit=limit,
                workspace_id=workspace_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("Embedding rebuild failed")
            return {"error": "Embedding rebuild failed"}, 500


@embeddings_ns.route("/search")
class EmbeddingsSearch(ForgeResource):
    @token_required
    @require_access("vector")
    def post(self):
        body = request.get_json(silent=True) or {}
        query = (body.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}, 400

        limit = _parse_limit_cap(body.get("limit", 10), default=10, cap=50)
        kinds = body.get("kinds")
        workspace_id = (body.get("workspace_id") or body.get("workspaceId") or "").strip() or None
        domain_id_raw = body.get("domain_id") or body.get("domainId")
        origin = (body.get("origin") or "").strip() or None
        model_table_id = _parse_model_table_id(body.get("modelTableId"))
        source_table_name = (body.get("sourceTableName") or "").strip() or None
        min_score = _parse_min_score(body.get("minScore"))
        domain_id = _parse_model_table_id(domain_id_raw)

        try:
            service = EmbeddingSearchService()
            result = service.search(
                query=query,
                limit=limit,
                kinds=kinds,
                workspace_id=workspace_id,
                domain_id=domain_id,
                origin=origin,
                model_table_id=model_table_id,
                source_table_name=source_table_name,
                min_score=min_score,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("Embedding search failed")
            return {"error": "Embedding search failed"}, 500


@embeddings_ns.route("/domains/upsert")
class EmbeddingsDomainUpsert(ForgeResource):
    @token_required
    @require_access("vector", role="admin")
    def post(self):
        body = request.get_json(silent=True) or {}
        workspace_id = (body.get("workspace_id") or "").strip()
        if not workspace_id:
            return {"error": "workspace_id is required"}, 400
        force = _parse_bool(body.get("force"), False)

        try:
            service = DomainEmbeddingService()
            result = service.upsert_domain_profiles(workspace_id=workspace_id, force=force)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("Domain embedding upsert failed")
            return {"error": "Domain embedding upsert failed"}, 500


@embeddings_ns.route("/columns/upsert")
class EmbeddingsColumnUpsert(ForgeResource):
    @token_required
    @require_access("vector", role="admin")
    def post(self):
        body = request.get_json(silent=True) or {}
        workspace_id = (body.get("workspace_id") or body.get("workspaceId") or "").strip()
        if not workspace_id:
            return {"error": "workspace_id is required"}, 400
        limit = _parse_limit(body.get("limit", 0))

        try:
            service = EmbeddingIndexService()
            result = service.upsert_workspace_columns(workspace_id=workspace_id, limit=limit)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("Column embedding upsert failed")
            return {"error": "Column embedding upsert failed"}, 500

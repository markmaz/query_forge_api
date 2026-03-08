# app/routes/query_forge_routes.py
from __future__ import annotations

import logging
import re

from flask import current_app, request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id, int_arg
from app.services.domain_resolver import DomainResolver
from app.services.domains.domain_resolver_service import DomainResolverService
from app.services.embedding.embedding_search_service import EmbeddingSearchService
from app.services.exports.export_policy import build_qf_export_policy, qf_rowcount_signature, store_cached_rowcount
from app.services.nlp.dictionary_ner import extract_signals as extract_dictionary_signals
from app.services.nlp.ed_ner import extract_signals as extract_ed_signals
from app.services.nlp.nlp_to_vector import build_vector_search_request
from app.services.query_forge_service import QueryForgeService
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder

logger = logging.getLogger(__name__)
query_forge_ns = Namespace("query", description="Query Forge query")

def _handle_service_error(e: ForgeError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400

_DATASOURCE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _resolve_analytics_executor(datasource_name: str | None):
    """Return the analytics ``SQLExecutor`` for *datasource_name* from the registry.

    Falls back to ``"primary"`` when *datasource_name* is ``None`` or empty.
    Returns ``None`` if the registry is unavailable (startup failure).

    Datasource selection is restricted to admin users only (FIND-018).  The
    datasource name is validated against ``^[A-Za-z0-9_\\-]{1,64}$`` before the
    registry lookup to prevent injection and information leakage (FIND-023).

    :param datasource_name: Name of the desired analytics datasource, or ``None``.
    :returns: ``SQLExecutor`` instance or ``None``.
    :raises ForgeError: 403 if the caller is not an admin and a non-default datasource
        is requested; 400 if the name fails validation; 404 if the datasource is not
        registered.
    """
    from flask import g as _g

    registry = current_app.extensions.get("analytics_registry")
    if registry is None:
        return None

    # When no datasource is specified the default ("primary") is used and no
    # admin check is required — the workspace-default path is unchanged.
    if not datasource_name:
        try:
            return registry.get("primary")
        except KeyError:
            return None

    # FIND-023: validate name format before any registry lookup so the user-supplied
    # value cannot appear verbatim in error messages or logs.
    if not _DATASOURCE_NAME_RE.match(datasource_name):
        raise ForgeError("Invalid datasource name", status_code=400)

    # FIND-018: datasource selection requires the admin role.
    if not getattr(_g, "is_admin", False):
        raise ForgeError("Datasource selection requires admin role", status_code=403)

    try:
        return registry.get(datasource_name)
    except KeyError:
        raise ForgeError("Datasource not found", status_code=404)


@query_forge_ns.route("/")
class QueryForgeRun(ForgeResource):
    @token_required
    def post(self):
        try:
            workspace_id = extract_workspace_id()

            mode = (request.args.get("mode") or "preview").strip().lower()
            limit = int_arg("limit", 200)
            offset = int_arg("offset", 0)

            # Optional analytics datasource override.
            # Application metadata queries (ORM, Peewee) are never routed here.
            datasource_name = (request.args.get("datasource") or "").strip() or None

            raw = request.get_json(silent=True) or {}
            if not isinstance(raw, dict):
                raise ForgeError("Invalid JSON body", status_code=400)

            ctx = WorkspaceContextBuilder().build(workspace_id)
            domain_resolver = DomainResolver(workspace_id=workspace_id)

            # Determine which SQL executor to use for analytics query execution.
            # When a named datasource is requested via the query param, use the
            # analytics registry.  Otherwise fall through to the workspace executor.
            analytics_executor = _resolve_analytics_executor(datasource_name)
            sql_exec = analytics_executor if analytics_executor is not None else ctx.sql_exec

            svc = QueryForgeService(executor=sql_exec, domain_resolver=domain_resolver)
            out = svc.run(raw_query=raw, mode=mode, limit=limit, offset=offset)
            signature = qf_rowcount_signature(out.sql, out.params)
            store_cached_rowcount(signature, out.total)

            return {
                "sql": out.sql,
                "sqlRendered": out.qf_rendered_sql,
                "params": out.params,
                "rows": out.rows,
                "columns": out.columns,
                "total": out.total,
                "totalRowCount": out.total,
                "export": build_qf_export_policy(out.total),
                "rowCountSignature": signature,
                "limit": out.limit,
                "offset": out.offset,
            }, 200

        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Query Forge query run failed")
            return {"error": "Query Forge query run failed"}, 500


@query_forge_ns.route("/plan")
class QueryForgePlan(ForgeResource):
    @token_required
    def post(self):
        try:
            workspace_id = extract_workspace_id()
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ForgeError("Invalid JSON body", status_code=400)

            text = (payload.get("text") or payload.get("prompt") or "").strip()
            if not text:
                raise ForgeError("text is required", status_code=400)
            domain_id = payload.get("domain_id")

            nlp_response = _run_nlp_extract(workspace_id, text, domain_id)
            vector_request = build_vector_search_request(nlp_response)
            vector_response = _run_vector_search(vector_request)

            table_hits = _table_hits_from_vector(vector_response)
            domain_resolution = DomainResolverService().resolve_from_table_hits(
                workspace_id=workspace_id,
                table_hits=table_hits,
            )

            sql_json = {
                "meta": {"tool": "query_builder", "prompt": text},
                "input": {"prompt": text},
            }

            return {
                "sqlJson": sql_json,
                "explain": {
                    "nlp": nlp_response,
                    "vector_request": vector_request,
                    "vector": vector_response,
                    "domain_resolution": domain_resolution,
                    "sql": None,
                },
            }, 200

        except ForgeError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Query Forge query plan failed")
            return {"error": "Query Forge query plan failed"}, 500


def _run_nlp_extract(workspace_id: str, text: str, domain_id: object | None) -> dict:
    if domain_id is not None:
        result = extract_dictionary_signals(workspace_id, int(domain_id), text)
        return {
            "workspace_id": workspace_id,
            "text": result.get("text", text),
            "intent": result.get("intent"),
            "entities": [result["entity"]] if result.get("entity") else [],
            "filters": result.get("filters", []),
            "domain_hints": [int(domain_id)],
            "debug": result.get("debug", {}),
        }

    result = extract_ed_signals(text)
    filters = [
        {"column_key": f.get("column"), "op": f.get("op"), "value": f.get("value")}
        for f in result.get("filters", [])
        if f.get("column")
    ]
    return {
        "workspace_id": workspace_id,
        "text": result.get("text", text),
        "intent": "COUNT" if result.get("metric") == "COUNT" else None,
        "entities": sorted({f["column_key"] for f in filters if f.get("column_key")}),
        "filters": filters,
        "domain_hints": _domain_hints(workspace_id, text),
        "debug": result.get("debug", {}),
    }


def _domain_hints(workspace_id: str, text: str) -> list[int]:
    if not workspace_id or not text:
        return []
    try:
        search = EmbeddingSearchService()
        results = search.search(query=text, kinds=["domain"], workspace_id=workspace_id, limit=5)
        hints: list[int] = []
        for item in results.get("results", []):
            domain_id = item.get("domainId")
            if domain_id is None:
                continue
            value = int(domain_id)
            if value not in hints:
                hints.append(value)
        return hints
    except Exception:
        logger.exception("Domain hint search failed")
        return []


def _run_vector_search(vector_request: dict) -> dict:
    query = ((vector_request.get("query") or {}).get("text") or "").strip()
    if not query:
        raise ForgeError("query is required", status_code=400)

    targets = vector_request.get("targets") or ["COLUMN", "TABLE"]
    kinds = []
    for target in targets:
        if not target:
            continue
        kinds.append(str(target).lower())

    domain_ids = vector_request.get("domain_ids") or []
    domain_id = domain_ids[0] if len(domain_ids) == 1 else None

    service = EmbeddingSearchService()
    return service.search(
        query=query,
        limit=vector_request.get("limit"),
        kinds=kinds,
        workspace_id=vector_request.get("workspace_id"),
        domain_id=domain_id,
        min_score=vector_request.get("min_score"),
    )


def _table_hits_from_vector(vector_response: dict) -> list[dict]:
    hits: list[dict] = []
    for item in vector_response.get("results", []) or []:
        kind = item.get("kind")
        if kind not in {"column", "table"}:
            continue
        table_id = item.get("workspaceTableId") or item.get("workspace_table_id")
        if table_id is None:
            continue
        try:
            table_id_int = int(table_id)
        except Exception:
            continue
        hits.append(
            {
                "workspace_table_id": table_id_int,
                "score": float(item.get("score") or 0.0),
                "table_name": item.get("tableName") or item.get("sourceTableName"),
            }
        )
    return hits

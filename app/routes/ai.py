from __future__ import annotations

import logging

import requests
from flask import current_app, request
from flask_restx import Namespace
from flask_restx import Resource
from pydantic import ValidationError

from app.decorators.security import token_required
from app.decorators.rbac import require_access, public
from app.exceptions.forge_error import ForgeError
from app.models.query.ai_suggest import SuggestAPIResponse, SuggestRequest
from app.routes.request_helpers import extract_workspace_id
from app.services.embedding.embedding_search_service import EmbeddingSearchService
from app.services.ai_suggest import AISuggestService, InvalidModelResponseError
from app.services.semantic.plan import PlanService

logger = logging.getLogger(__name__)

ai_ns = Namespace("ai", description="AI planner endpoints")
RETRIEVAL_LIMIT = 20
TOP_DOMAIN_CANDIDATES = 3
TOP_COLUMN_CANDIDATES = 25
TOP_TABLE_CANDIDATES = 10

DEPRECATION_HEADERS = {
    "X-QueryForge-Deprecated": "true",
    "X-QueryForge-Replacement": "/api/v1/semantic/plan",
}


def _build_service() -> AISuggestService:
    return AISuggestService(
        base_url=current_app.config.get("VLLM_BASE_URL"),
        model=current_app.config.get("VLLM_MODEL"),
        timeout=current_app.config.get("VLLM_TIMEOUT"),
    )


def _is_candidates_empty(suggest_request: SuggestRequest) -> bool:
    candidates = suggest_request.candidates
    if candidates is None:
        return True
    return not candidates.columns and not candidates.tables


def _retrieval_kinds(suggest_request: SuggestRequest) -> list[str]:
    if suggest_request.mode == "domains":
        return ["domain"]
    selected_domain_id = (
        suggest_request.domainContext.selectedDomainId
        if suggest_request.domainContext
        else None
    )
    if selected_domain_id is not None:
        return ["column", "table"]
    return ["domain", "column", "table"]


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_reason_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _trim_description(value: object) -> str:
    text = str(value or "").strip()
    if len(text) > 240:
        return text[:240]
    return text


def _selected_domain_id(suggest_request: SuggestRequest) -> int | None:
    selected_domain_id = (
        suggest_request.domainContext.selectedDomainId
        if suggest_request.domainContext
        else None
    )
    if selected_domain_id is None and isinstance(suggest_request.currentSqlJson, dict):
        selected_domain_id = _as_int(suggest_request.currentSqlJson.get("domainId"))
    return selected_domain_id


def _inject_mode_placeholders(sqljson: dict, *, mode: str) -> dict:
    payload = dict(sqljson or {})
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    placeholders = {
        "domains": None,
        "columns": None,
        "filters": None,
        "aggregation": None,
        "data_prep": None,
    }
    active_mode = str(mode or "").strip().lower()
    if active_mode in placeholders:
        placeholders[active_mode] = {"status": "requested"}
    meta["semantic_plan_placeholders"] = placeholders
    payload["meta"] = meta
    return payload


def _plan_response_as_suggest(
    *,
    suggest_request: SuggestRequest,
    debug: bool,
) -> SuggestAPIResponse:
    semantic_result = PlanService().plan(
        {
            "workspace_id": suggest_request.workspaceId,
            "prompt": suggest_request.prompt,
            "domain_id": _selected_domain_id(suggest_request),
            "debug": debug,
        },
        include_llm=True,
    )
    llm_plan = semantic_result.get("llm_plan") if isinstance(semantic_result, dict) else {}
    sqljson = llm_plan.get("sql_json") if isinstance(llm_plan, dict) and isinstance(llm_plan.get("sql_json"), dict) else {}
    if not isinstance(sqljson, dict):
        sqljson = {}
    sqljson = _inject_mode_placeholders(sqljson, mode=suggest_request.mode)
    notes = list(llm_plan.get("notes") or []) if isinstance(llm_plan, dict) else []
    explanation = "; ".join(str(item).strip() for item in notes if str(item).strip()) or "Semantic planner response"
    confidence = _as_float((llm_plan or {}).get("confidence"), default=0.5)
    confidence = max(0.0, min(1.0, confidence))
    model_name = str((llm_plan or {}).get("model") or current_app.config.get("VLLM_MODEL") or "semantic-plan").strip()
    return SuggestAPIResponse.model_validate(
        {
            "edits": _sqljson_to_suggest_edits(sqljson),
            "explanation": explanation,
            "confidence": confidence,
            "sqlJson": sqljson,
            "debug": {
                "model": model_name,
                "attempts": 1,
            },
        }
    )


def _column_signature_dict(item: dict) -> str:
    return "|".join(
        [
            str(item.get("workspaceTableId")),
            str(item.get("columnName") or "").strip().lower(),
        ]
    )


def _apply_retrieval_candidates(suggest_request: SuggestRequest) -> tuple[SuggestRequest, set[int], set[str], dict]:
    selected_domain_id = (
        suggest_request.domainContext.selectedDomainId
        if suggest_request.domainContext
        else None
    )
    kinds = _retrieval_kinds(suggest_request)
    retrieval = EmbeddingSearchService().search(
        query=suggest_request.prompt,
        workspace_id=suggest_request.workspaceId,
        domain_id=selected_domain_id,
        kinds=kinds,
        limit=RETRIEVAL_LIMIT,
    )

    result_sets = retrieval.get("results") or {}
    retrieved_domains = result_sets.get("domains") or []
    retrieved_columns = result_sets.get("columns") or []
    retrieved_tables = result_sets.get("tables") or []

    domain_candidates = []
    for item in retrieved_domains[:TOP_DOMAIN_CANDIDATES]:
        domain_id = _as_int(item.get("domainId"))
        if domain_id is None:
            continue
        domain_name = str(item.get("domainName") or "").strip()
        domain_kind = str(item.get("domainKind") or "").strip()
        domain_candidates.append(
            {
                "domainId": domain_id,
                "name": domain_name,
                "description": domain_kind,
                "domainName": domain_name,
                "domainKind": domain_kind or None,
                "score": _as_float(item.get("score")),
            }
        )

    table_candidates = []
    for item in retrieved_tables[:TOP_TABLE_CANDIDATES]:
        table_name = str(item.get("tableName") or "").strip()
        if not table_name:
            continue
        model_table_id = _as_int(item.get("modelTableId"))
        table_candidates.append(
            {
                "tableId": model_table_id,
                "tableName": table_name,
                "modelTableId": model_table_id,
                "score": _as_float(item.get("score")),
                "reasons": _to_reason_list(item.get("reasons")),
            }
        )

    column_candidates = []
    for item in retrieved_columns[:TOP_COLUMN_CANDIDATES]:
        table_name = str(item.get("tableName") or "").strip()
        column_name = str(item.get("columnName") or "").strip()
        if not table_name or not column_name:
            continue
        model_column_id = _as_int(item.get("modelColumnId"))
        workspace_table_id = _as_int(item.get("workspaceTableId"))
        model_table_id = _as_int(item.get("modelTableId"))
        column_candidates.append(
            {
                "modelColumnId": model_column_id,
                "columnName": column_name,
                "workspaceTableId": workspace_table_id,
                "modelTableId": model_table_id,
                "modelTableName": table_name,
                "label": column_name,
                "description": _trim_description(item.get("description")),
                "dataType": item.get("dataType"),
                "score": _as_float(item.get("score")),
                "reasons": _to_reason_list(item.get("reasons")),
            }
        )

    payload = suggest_request.model_dump(mode="json")
    payload["candidates"] = {
        "tables": table_candidates,
        "columns": column_candidates,
    }
    if domain_candidates:
        domain_context = payload.get("domainContext") or {}
        domain_context["domainCandidates"] = domain_candidates
        if domain_context.get("selectedDomainId") is None and selected_domain_id is not None:
            domain_context["selectedDomainId"] = selected_domain_id
        payload["domainContext"] = domain_context

    updated = SuggestRequest.model_validate(payload)
    valid_domain_ids = {int(item["domainId"]) for item in domain_candidates}
    valid_column_keys = {_column_signature_dict(item) for item in column_candidates}
    summary = {
        "domains": len(domain_candidates),
        "tables": len(table_candidates),
        "columns": len(column_candidates),
    }
    return updated, valid_domain_ids, valid_column_keys, summary


def _legacy_suggest_response(suggest_request: SuggestRequest) -> SuggestAPIResponse:
    retrieval_used = False
    valid_domain_ids: set[int] = set()
    valid_column_keys: set[str] = set()
    candidate_counts = {
        "domains": len(suggest_request.domainContext.domainCandidates)
        if suggest_request.domainContext
        else 0,
        "tables": len(suggest_request.candidates.tables) if suggest_request.candidates else 0,
        "columns": len(suggest_request.candidates.columns) if suggest_request.candidates else 0,
    }
    if _is_candidates_empty(suggest_request):
        (
            suggest_request,
            valid_domain_ids,
            valid_column_keys,
            candidate_counts,
        ) = _apply_retrieval_candidates(suggest_request)
        retrieval_used = True

    logger.info(
        "AI suggest legacy fallback retrieval_used=%s domains=%s tables=%s columns=%s",
        retrieval_used,
        candidate_counts["domains"],
        candidate_counts["tables"],
        candidate_counts["columns"],
    )

    service = _build_service()
    return service.suggest(
        suggest_request,
        valid_domain_ids=valid_domain_ids if retrieval_used else None,
        valid_column_keys=valid_column_keys if retrieval_used else None,
    )


@ai_ns.route("/suggest")
class AISuggest(Resource):
    @token_required
    @require_access("ai")
    def post(self) -> tuple[dict, int]:
        workspace_id = extract_workspace_id()
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}
        body["workspaceId"] = workspace_id

        try:
            debug = bool(body.pop("debug", False))
            suggest_request = SuggestRequest.model_validate(body)
        except ValidationError as exc:
            return {"error": "Invalid request", "details": exc.errors(include_url=False)}, 400

        logger.warning("ai/suggest is deprecated; routing through semantic/plan")
        try:
            result = _plan_response_as_suggest(
                suggest_request=suggest_request,
                debug=debug,
            )
            return result.model_dump(mode="json"), 200, DEPRECATION_HEADERS
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code, DEPRECATION_HEADERS
        except (RuntimeError, TypeError, ValueError, requests.RequestException):
            logger.exception("ai/suggest semantic bridge failed; falling back to legacy ai_suggest_service")
            try:
                result = _legacy_suggest_response(suggest_request)
                return result.model_dump(mode="json"), 200, DEPRECATION_HEADERS
            except InvalidModelResponseError as exc:
                logger.error("AI suggest invalid model response: %s", exc.details)
                return {"error": "Invalid model response", "details": exc.details}, 500, DEPRECATION_HEADERS
            except requests.RequestException as exc:
                logger.error("AI suggest upstream request failed: %s", exc)
                return {"error": "vLLM request failed", "details": str(exc)}, 502, DEPRECATION_HEADERS
            except (RuntimeError, TypeError, ValueError) as exc:
                logger.exception("AI suggest failed unexpectedly")
                return {"error": "AI suggest failed", "details": str(exc)}, 500, DEPRECATION_HEADERS


def _sql_column_key_from_field(field: object) -> dict | None:
    if not isinstance(field, dict):
        return None
    column_name = str(field.get("columnName") or "").strip()
    if not column_name:
        return None
    return {
        "modelColumnId": _as_int(field.get("modelColumnId")),
        "columnName": column_name,
        "workspaceTableId": _as_int(field.get("workspaceTableId")),
        "exprId": field.get("exprId"),
        "alias": field.get("alias"),
    }


def _flatten_filter_conditions(node: object) -> list[dict]:
    if not isinstance(node, dict):
        return []
    node_type = str(node.get("type") or "").strip().lower()
    if node_type == "condition":
        return [node]
    out: list[dict] = []
    for child in list(node.get("children") or []):
        out.extend(_flatten_filter_conditions(child))
    return out


def _map_filter_operator(op: object) -> str | None:
    token = str(op or "").strip().lower()
    mapping = {
        "equals": "equals",
        "=": "equals",
        "==": "equals",
        "eq": "equals",
        "not_equals": "not_equals",
        "not_equal": "not_equals",
        "ne": "not_equals",
        "!=": "not_equals",
        "<>": "not_equals",
        "contains": "contains",
        "like": "contains",
        "starts_with": "starts_with",
        "startswith": "starts_with",
        "prefix": "starts_with",
        "in": "in",
        "not_in": "not_in",
        "not in": "not_in",
        "gt": "gt",
        ">": "gt",
        "gte": "gte",
        ">=": "gte",
        "lt": "lt",
        "<": "lt",
        "lte": "lte",
        "<=": "lte",
        "between": "between",
        "is_null": "is_null",
        "is null": "is_null",
        "not_exists": "is_null",
        "is_not_null": "is_not_null",
        "is not null": "is_not_null",
        "exists": "is_not_null",
    }
    return mapping.get(token)


def _map_aggregate_func(func: object) -> str | None:
    token = str(func or "").strip().lower()
    mapping = {
        "count_distinct": "count_distinct",
        "countdistinct": "count_distinct",
        "count": "count",
        "sum": "sum",
        "avg": "avg",
        "average": "avg",
    }
    return mapping.get(token)


def _sqljson_to_suggest_edits(sqljson: object) -> list[dict]:
    if not isinstance(sqljson, dict):
        return []
    edits: list[dict] = []

    domain_id = _as_int(sqljson.get("domainId"))
    if domain_id is not None:
        edits.append({"op": "setDomain", "domainId": domain_id})

    for item in list(sqljson.get("columns") or []):
        if not isinstance(item, dict):
            continue
        col = _sql_column_key_from_field(item.get("field"))
        if col is None:
            continue
        edits.append({"op": "addSelect", "col": col, "alias": item.get("alias")})

    for condition in _flatten_filter_conditions(sqljson.get("filters")):
        col = _sql_column_key_from_field(condition.get("field"))
        operator = _map_filter_operator(condition.get("op"))
        if col is None or operator is None:
            continue
        edits.append(
            {
                "op": "addFilter",
                "col": col,
                "operator": operator,
                "value": condition.get("value"),
            }
        )

    for item in list(sqljson.get("groupBy") or []):
        if not isinstance(item, dict):
            continue
        col = _sql_column_key_from_field(item.get("field"))
        if col is None:
            continue
        edits.append({"op": "addGroupBy", "col": col})

    for idx, item in enumerate(list(sqljson.get("aggregates") or []), start=1):
        if not isinstance(item, dict):
            continue
        func = _map_aggregate_func(item.get("func"))
        if func is None:
            continue
        col = _sql_column_key_from_field(item.get("field"))
        alias = str(item.get("alias") or "").strip() or f"{func}_{idx}"
        edits.append(
            {
                "op": "addAggregate",
                "func": func,
                "col": col,
                "alias": alias,
            }
        )

    for item in list(sqljson.get("sort") or []):
        if not isinstance(item, dict):
            continue
        col = _sql_column_key_from_field(item.get("field"))
        if col is None:
            continue
        direction = str(item.get("dir") or "").strip().lower()
        if direction not in {"asc", "desc"}:
            direction = "asc"
        edits.append({"op": "addSort", "col": col, "dir": direction})
    return edits


@ai_ns.route("/suggest-semantic-adapter")
class AISuggestSemanticAdapter(Resource):
    @token_required
    @require_access("ai")
    def post(self) -> tuple[dict, int]:
        workspace_id = extract_workspace_id()
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}

        debug = bool(body.pop("debug", False))
        body["workspaceId"] = workspace_id

        try:
            suggest_request = SuggestRequest.model_validate(body)
        except ValidationError as exc:
            return {"error": "Invalid request", "details": exc.errors(include_url=False)}, 400

        try:
            payload = _plan_response_as_suggest(
                suggest_request=suggest_request,
                debug=debug,
            )
            return payload.model_dump(mode="json"), 200, DEPRECATION_HEADERS
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code, DEPRECATION_HEADERS
        except (RuntimeError, TypeError, ValueError, requests.RequestException) as exc:
            logger.exception("AI semantic adapter failed unexpectedly")
            return {"error": "AI semantic adapter failed", "details": str(exc)}, 500, DEPRECATION_HEADERS


@ai_ns.route("/health")
class AIHealth(Resource):
    @public
    def get(self) -> tuple[dict, int]:
        service = _build_service()
        try:
            payload = service.health()
            return {
                "status": "ok",
                "model": service.model,
                "upstream": payload,
            }, 200
        except requests.RequestException as exc:
            logger.error("AI health check failed: %s", exc)
            return {"status": "error", "error": "vLLM unavailable", "details": str(exc)}, 503

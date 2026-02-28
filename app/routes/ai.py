from __future__ import annotations

import logging

import requests
from flask import current_app, request
from flask_restx import Namespace, Resource
from pydantic import ValidationError

from app.decorators.security import token_required
from app.models.ai_suggest import SuggestRequest
from app.routes._route_utils import get_workspace_id_from_header
from app.services.embedding.embedding_search_service import EmbeddingSearchService
from app.services.ai_suggest_service import AISuggestService, InvalidModelResponseError

logger = logging.getLogger(__name__)

ai_ns = Namespace("ai", description="AI planner endpoints")
RETRIEVAL_LIMIT = 20
TOP_DOMAIN_CANDIDATES = 3
TOP_COLUMN_CANDIDATES = 25
TOP_TABLE_CANDIDATES = 10


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


@ai_ns.route("/suggest")
class AISuggest(Resource):
    @token_required
    def post(self) -> tuple[dict, int]:
        workspace_id = get_workspace_id_from_header()
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}
        body["workspaceId"] = workspace_id

        try:
            suggest_request = SuggestRequest.model_validate(body)
        except ValidationError as exc:
            return {"error": "Invalid request", "details": exc.errors(include_url=False)}, 400

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
            "AI suggest retrieval_used=%s domains=%s tables=%s columns=%s",
            retrieval_used,
            candidate_counts["domains"],
            candidate_counts["tables"],
            candidate_counts["columns"],
        )

        service = _build_service()
        try:
            result = service.suggest(
                suggest_request,
                valid_domain_ids=valid_domain_ids if retrieval_used else None,
                valid_column_keys=valid_column_keys if retrieval_used else None,
            )
            return result.model_dump(mode="json"), 200
        except InvalidModelResponseError as exc:
            logger.error("AI suggest invalid model response: %s", exc.details)
            return {"error": "Invalid model response", "details": exc.details}, 500
        except requests.RequestException as exc:
            logger.error("AI suggest upstream request failed: %s", exc)
            return {"error": "vLLM request failed", "details": str(exc)}, 502
        except Exception as exc:
            logger.exception("AI suggest failed unexpectedly")
            return {"error": "AI suggest failed", "details": str(exc)}, 500


@ai_ns.route("/health")
class AIHealth(Resource):
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

from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.services.embedding.embedding_search_service import EmbeddingSearchService
from app.services.nlp.dictionary_ner import extract_signals as extract_dictionary_signals
from app.services.nlp.ed_ner import extract_signals as extract_ed_signals
from app.services.nlp.nlp_to_vector import build_vector_search_request

logger = logging.getLogger(__name__)

nlp_ns = Namespace("nlp", description="NLP extraction")


@nlp_ns.route("/extract")
class NlpExtract(Resource):
    @token_required
    def post(self):
        body = request.get_json(silent=True) or {}
        response, error = _run_nlp_extract(body)
        if error:
            return error
        return response, 200


@nlp_ns.route("/extract-and-search")
class NlpExtractAndSearch(Resource):
    @token_required
    def post(self):
        body = request.get_json(silent=True) or {}
        response, error = _run_nlp_extract(body)
        if error:
            return error

        try:
            vector_request = build_vector_search_request(response)
            vector_response = _run_vector_search(vector_request)
            return {
                "nlp": response,
                "vector_request": vector_request,
                "vector": vector_response,
            }, 200
        except Exception:
            logger.exception("NLP extract-and-search failed")
            return {"error": "NLP extract-and-search failed"}, 500


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
        logger.exception("NLP domain hint search failed")
        return []


def _run_nlp_extract(body: dict) -> tuple[dict, tuple[dict, int] | None]:
    text = (body.get("text") or "").strip()
    workspace_id = (body.get("workspace_id") or "").strip()
    domain_id = body.get("domain_id")

    if not text:
        return {}, ({"error": "text is required"}, 400)
    if not workspace_id:
        return {}, ({"error": "workspace_id is required"}, 400)

    try:
        if domain_id is not None:
            result = extract_dictionary_signals(workspace_id, int(domain_id), text)
            response = {
                "workspace_id": workspace_id,
                "text": result.get("text", text),
                "intent": result.get("intent"),
                "entities": [result["entity"]] if result.get("entity") else [],
                "filters": result.get("filters", []),
                "domain_hints": [int(domain_id)],
                "debug": result.get("debug", {}),
            }
        else:
            result = extract_ed_signals(text)
            filters = [
                {"column_key": f.get("column"), "op": f.get("op"), "value": f.get("value")}
                for f in result.get("filters", [])
                if f.get("column")
            ]
            response = {
                "workspace_id": workspace_id,
                "text": result.get("text", text),
                "intent": "COUNT" if result.get("metric") == "COUNT" else None,
                "entities": sorted({f["column_key"] for f in filters if f.get("column_key")}),
                "filters": filters,
                "domain_hints": _domain_hints(workspace_id, text),
                "debug": result.get("debug", {}),
            }
        return response, None
    except Exception:
        logger.exception("NLP extraction failed")
        return {}, ({"error": "NLP extraction failed"}, 500)


def _run_vector_search(vector_request: dict) -> dict:
    query = ((vector_request.get("query") or {}).get("text") or "").strip()
    if not query:
        return {"error": "query is required"}

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

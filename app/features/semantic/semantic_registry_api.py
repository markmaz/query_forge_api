from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import int_arg
from app.services.semantic.semantic_registry_service import SemanticRegistryService

from .schemas import register_registry_models

logger = logging.getLogger(__name__)

semantic_registry_ns = Namespace("semantic-registry", description="Semantic registry endpoints")
semantic_registry_entry_model = register_registry_models(semantic_registry_ns)


@semantic_registry_ns.route("")
class SemanticRegistryCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_registry_ns.doc(
        params={
            "q": "Search concept_key and description",
            "semantic_type": "Filter by semantic_type",
            "entity": "Filter by entity",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            result = SemanticRegistryService().list_entries(
                q=(request.args.get("q") or None),
                semantic_type=(request.args.get("semantic_type") or None),
                entity=(request.args.get("entity") or None),
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 25),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry list failed")
            return {"error": "semantic registry list failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticRegistryService().create_entry(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry create failed")
            return {"error": "semantic registry create failed"}, 500


@semantic_registry_ns.route("/<int:entry_id>")
class SemanticRegistryById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, entry_id: int):
        try:
            row = SemanticRegistryService().get_entry(entry_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry get failed")
            return {"error": "semantic registry get failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def patch(self, entry_id: int):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticRegistryService().update_entry(entry_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry update failed")
            return {"error": "semantic registry update failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, entry_id: int):
        try:
            SemanticRegistryService().delete_entry(entry_id)
            return {"deleted": True, "id": entry_id}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry delete failed")
            return {"error": "semantic registry delete failed"}, 500

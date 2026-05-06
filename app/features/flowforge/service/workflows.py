from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.models import WorkflowDefinition, WorkflowValidationResult
from app.features.flowforge.seed import THERAPIST_ROUTING_RUN_EVENTS, THERAPIST_ROUTING_WORKFLOW

logger = logging.getLogger(__name__)

FLOWFORGE_TRIGGER_NODE_TYPES = {"schedule_trigger", "webhook_trigger", "file_watch_trigger"}
FLOWFORGE_DATA_MOVEMENT_NODE_TYPES = {"query_extract", "export", "import", "map_transform"}
FLOWFORGE_SUPPORTED_NODE_TYPES = {
    *FLOWFORGE_TRIGGER_NODE_TYPES,
    "intake",
    "scoring",
    "filter",
    "ranking",
    "human_task",
    "matching",
    "notification",
    "wait",
    "end",
    "decision",
    "assignment",
    "event_capture",
    "iterator",
    *FLOWFORGE_DATA_MOVEMENT_NODE_TYPES,
    "approval",
}
QUERY_EXTRACT_SOURCE_KEYS = {"saved_query_id", "semantic_plan_id", "query_builder_artifact_id"}
QUERY_EXTRACT_FORBIDDEN_KEYS = {"sql", "raw_sql", "query", "query_text", "statement"}
EXPORT_DESTINATION_KEYS = {"destination_key", "destination_id"}
IMPORT_SOURCE_KEYS = {"source_key", "source_id", "resource_set_id"}


class FlowForgeWorkflowServiceMixin:
    def list_definitions(self, *, workspace_id: str) -> list[WorkflowDefinition]:
        try:
            persisted = [
                self._serialize_workflow_definition(row)
                for row in self._workflow_repository.list_workflow_definitions(workspace_id=workspace_id)
            ]
        except SQLAlchemyError:
            logger.exception("flowforge_workflow_definition_list_failed workspace_id=%s", workspace_id)
            persisted = []
        return persisted + [deepcopy(THERAPIST_ROUTING_WORKFLOW)]

    def get_definition(self, *, workspace_id: str, workflow_id: str) -> WorkflowDefinition | None:
        if workflow_id == THERAPIST_ROUTING_WORKFLOW["id"]:
            return deepcopy(THERAPIST_ROUTING_WORKFLOW)
        try:
            workflow_definition_id = int(workflow_id)
        except (TypeError, ValueError):
            return None
        row = self._workflow_repository.get_workflow_definition(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        if row is None:
            return None
        return self._serialize_workflow_definition(row)

    def create_workflow_definition(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> WorkflowDefinition:
        workflow_key = str(payload.get("workflow_key") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not workflow_key:
            raise ForgeError("workflow_key is required.", status_code=400)
        if not name:
            raise ForgeError("name is required.", status_code=400)
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {"nodes": [], "edges": []}
        validation = self.validate_graph(graph=graph)
        if not validation["valid"]:
            raise ForgeError("Workflow graph is invalid.", status_code=400, details=validation)
        workflow_definition_id = self._workflow_repository.create_workflow_definition(
            workspace_id=workspace_id,
            workflow_key=workflow_key,
            name=name,
            description=self._optional_string(payload.get("description")),
            created_by=self._optional_string(actor_user_id),
        )
        version = self.create_workflow_version(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            payload={"graph": graph, "settings": payload.get("settings") if isinstance(payload.get("settings"), dict) else {}},
            actor_user_id=actor_user_id,
        )
        return {
            "id": str(workflow_definition_id),
            "name": name,
            "description": self._optional_string(payload.get("description")) or "",
            "status": "draft",
            "graph": version["graph"],
        }
        return None

    def validate_graph(self, *, graph: dict[str, Any]) -> WorkflowValidationResult:
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        edges = graph.get("edges") if isinstance(graph, dict) else None
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(nodes, list) or not isinstance(edges, list):
            return {
                "valid": False,
                "errors": ["Graph must contain nodes and edges arrays."],
                "warnings": [],
            }
        if not nodes:
            errors.append("Graph must contain at least one node.")

        node_ids: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                errors.append("Every node must be an object.")
                continue
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                errors.append("Every node must have a non-empty id.")
                continue
            if node_id in node_ids:
                errors.append(f"Duplicate node id '{node_id}'.")
            node_ids.add(node_id)
            if not str(node.get("type") or "").strip():
                errors.append(f"Node '{node_id}' must have a type.")
                continue
            node_type = str(node.get("type") or "").strip()
            if node_type not in FLOWFORGE_SUPPORTED_NODE_TYPES:
                errors.append(f"Node '{node_id}' has unsupported type '{node_type}'.")
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            node_config = {**data, **config}
            self._validate_node_config(
                node_id=node_id,
                node_type=node_type,
                node_config=node_config,
                errors=errors,
                warnings=warnings,
            )

        has_cycle = False
        incoming_counts = {node_id: 0 for node_id in node_ids}
        outgoing_counts = {node_id: 0 for node_id in node_ids}
        for edge in edges:
            if not isinstance(edge, dict):
                errors.append("Every edge must be an object.")
                continue
            edge_id = str(edge.get("id") or "<unknown>")
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            if source not in node_ids:
                errors.append(f"Edge {edge_id} has an unknown source.")
            if target not in node_ids:
                errors.append(f"Edge {edge_id} has an unknown target.")
            if source in outgoing_counts:
                outgoing_counts[source] += 1
            if target in incoming_counts:
                incoming_counts[target] += 1
            if source and target and self._path_exists(edges=edges, start=target, end=source):
                has_cycle = True

        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "").strip()
            node_type = str(node.get("type") or "").strip()
            if node_type in FLOWFORGE_TRIGGER_NODE_TYPES and incoming_counts.get(node_id, 0) > 0:
                errors.append(f"Trigger node '{node_id}' cannot have incoming edges.")
            if node_type in FLOWFORGE_TRIGGER_NODE_TYPES and outgoing_counts.get(node_id, 0) == 0:
                warnings.append(f"Trigger node '{node_id}' has no outgoing edge.")

        if has_cycle:
            warnings.append(
                "Graph contains a loop. FlowForge allows this, but runtime execution must use state-machine semantics."
            )

        return {"valid": not errors, "errors": errors, "warnings": warnings}

    def _validate_node_config(
        self,
        *,
        node_id: str,
        node_type: str,
        node_config: dict[str, Any],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        if node_type == "schedule_trigger":
            if not any(node_config.get(key) for key in ("schedule", "rrule", "interval_minutes", "cron")):
                errors.append(f"Schedule trigger '{node_id}' requires schedule, rrule, cron, or interval_minutes.")
        if node_type == "file_watch_trigger" and not any(node_config.get(key) for key in ("source_key", "source_id")):
            errors.append(f"File watch trigger '{node_id}' requires an allowlisted source_key or source_id.")
        if node_type == "query_extract":
            forbidden = sorted(key for key in QUERY_EXTRACT_FORBIDDEN_KEYS if node_config.get(key))
            if forbidden:
                errors.append(
                    f"Query extract node '{node_id}' cannot define raw SQL fields: {', '.join(forbidden)}."
                )
            if not any(node_config.get(key) for key in QUERY_EXTRACT_SOURCE_KEYS):
                errors.append(
                    f"Query extract node '{node_id}' requires saved_query_id, semantic_plan_id, or query_builder_artifact_id."
                )
        if node_type == "export" and not any(node_config.get(key) for key in EXPORT_DESTINATION_KEYS):
            errors.append(f"Export node '{node_id}' requires an allowlisted destination_key or destination_id.")
        if node_type == "import" and not any(node_config.get(key) for key in IMPORT_SOURCE_KEYS):
            errors.append(f"Import node '{node_id}' requires an allowlisted source_key/source_id or resource_set_id staging target.")
        if node_type == "map_transform" and not any(
            isinstance(node_config.get(key), (dict, list)) and node_config.get(key)
            for key in ("field_mapping", "mappings", "validations")
        ):
            warnings.append(f"Map transform node '{node_id}' has no field mapping or validation rules.")

    def get_run_inspector(self, *, workspace_id: str, workflow_id: str) -> dict[str, Any] | None:
        del workspace_id
        if workflow_id != THERAPIST_ROUTING_WORKFLOW["id"]:
            return None
        return {
            "workflow_id": workflow_id,
            "mode": "placeholder",
            "status": "not_started",
            "events": deepcopy(THERAPIST_ROUTING_RUN_EVENTS),
            "notes": [
                "Runtime persistence is intentionally not implemented yet.",
                "Future execution should persist state transitions and events before dispatching side effects.",
            ],
        }

    def list_workflow_versions(self, *, workspace_id: str, workflow_definition_id: int) -> list[dict[str, Any]]:
        rows = self._workflow_repository.list_workflow_versions(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        return [self._serialize_workflow_version(row) for row in rows]

    def create_workflow_version(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        definition = self._workflow_repository.get_workflow_definition(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        if definition is None:
            raise ForgeError(f"Workflow definition '{workflow_definition_id}' was not found.", status_code=404)
        graph = payload.get("graph") if isinstance(payload, dict) else None
        if not isinstance(graph, dict):
            raise ForgeError("graph must be an object.", status_code=400)
        validation = self.validate_graph(graph=graph)
        if not validation["valid"]:
            raise ForgeError("Workflow graph is invalid.", status_code=400, details=validation)
        existing_versions = self._workflow_repository.list_workflow_versions(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        next_version_number = max([int(row.get("version_number") or 0) for row in existing_versions] or [0]) + 1
        version_id = self._workflow_repository.create_workflow_version(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            version_number=next_version_number,
            graph=graph,
            created_by=self._optional_string(actor_user_id),
            version_status="draft",
            validation_status="valid",
            validation_result=validation,
            matching_policy_refs=payload.get("matching_policy_refs") if isinstance(payload.get("matching_policy_refs"), list) else [],
            settings=payload.get("settings") if isinstance(payload.get("settings"), dict) else {},
        )
        self._workflow_repository.set_current_draft_version(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            version_id=version_id,
            updated_by=self._optional_string(actor_user_id),
        )
        return {
            "id": version_id,
            "workspace_id": workspace_id,
            "workflow_definition_id": workflow_definition_id,
            "version_number": next_version_number,
            "version_status": "draft",
            "graph": graph,
            "validation_status": "valid",
            "validation_result": validation,
            "matching_policy_refs": payload.get("matching_policy_refs") if isinstance(payload.get("matching_policy_refs"), list) else [],
            "settings": payload.get("settings") if isinstance(payload.get("settings"), dict) else {},
        }

    def publish_workflow_version(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        version_id: int,
        actor_user_id: str,
    ) -> dict[str, Any]:
        row = self._workflow_repository.get_workflow_version(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            version_id=version_id,
        )
        if row is None:
            raise ForgeError(f"Workflow version '{version_id}' was not found.", status_code=404)
        if str(row.get("validation_status") or "") != "valid":
            raise ForgeError("Only valid workflow versions can be published.", status_code=400)
        self._workflow_repository.publish_workflow_version(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            version_id=version_id,
            published_by=actor_user_id,
        )
        published = dict(row)
        published["version_status"] = "published"
        return self._serialize_workflow_version(published)

    def delete_workflow_definition(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        actor_user_id: str,
    ) -> dict[str, Any]:
        definition = self._workflow_repository.get_workflow_definition(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        if definition is None:
            raise ForgeError(f"Workflow definition '{workflow_definition_id}' was not found.", status_code=404)
        archived = self._workflow_repository.archive_workflow_definition(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            archived_by=self._optional_string(actor_user_id),
        )
        if not archived:
            raise ForgeError(f"Workflow definition '{workflow_definition_id}' was not found.", status_code=404)
        return {"deleted": True, "workflow_definition_id": workflow_definition_id}

    def _path_exists(self, *, edges: list[Any], start: str, end: str) -> bool:
        adjacency: dict[str, list[str]] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            if source and target:
                adjacency.setdefault(source, []).append(target)

        pending = [start]
        seen: set[str] = set()
        while pending:
            node_id = pending.pop()
            if node_id == end:
                return True
            if node_id in seen:
                continue
            seen.add(node_id)
            pending.extend(adjacency.get(node_id, []))
        return False

    def _serialize_workflow_version(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "workflow_definition_id": row.get("workflow_definition_id"),
            "version_number": row.get("version_number"),
            "version_status": row.get("version_status"),
            "graph": row.get("graph") or row.get("graph_json") or {},
            "validation_status": row.get("validation_status"),
            "validation_result": row.get("validation_result") or row.get("validation_result_json") or {},
            "matching_policy_refs": row.get("matching_policy_refs") or row.get("matching_policy_refs_json") or [],
            "settings": row.get("settings") or row.get("settings_json") or {},
            "created_at": row.get("created_at"),
            "published_at": row.get("published_at"),
        }

    def _serialize_workflow_definition(self, row: dict[str, Any]) -> WorkflowDefinition:
        return {
            "id": str(row.get("id")),
            "name": row.get("name") or "",
            "description": row.get("description") or "",
            "status": row.get("status") or "draft",
            "graph": row.get("graph") or row.get("graph_json") or {"nodes": [], "edges": []},
        }

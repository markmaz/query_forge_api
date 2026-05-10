from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FlowForgeTriggerEvaluationServiceMixin:
    def _evaluate_integration_triggers(
        self,
        *,
        workspace_id: str,
        integration_config_id: int,
        normalized_payload: dict[str, Any],
    ) -> dict[str, Any]:
        triggers = [
            self._serialize_integration_trigger(row)
            for row in self._integration_repository.list_integration_triggers(
                workspace_id=workspace_id,
                integration_config_id=integration_config_id,
            )
            if bool(row.get("enabled"))
        ]
        evaluated = []
        matched = []
        for trigger in triggers:
            result = self._evaluate_trigger_condition(
                trigger_mode=str(trigger.get("trigger_mode") or "always"),
                condition=trigger.get("condition") or {},
                normalized_payload=normalized_payload,
            )
            entry = {
                "id": trigger.get("id"),
                "trigger_key": trigger.get("trigger_key"),
                "display_name": trigger.get("display_name"),
                "priority": trigger.get("priority"),
                "matched": result["matched"],
                "reason": result["reason"],
                "trigger_mode": trigger.get("trigger_mode"),
                "trigger_policy": trigger.get("trigger_policy"),
                "version_strategy": trigger.get("version_strategy"),
                "workflow_definition_id": trigger.get("workflow_definition_id"),
                "workflow_version_id": trigger.get("workflow_version_id"),
                "field_mapping": trigger.get("field_mapping") or {},
                "no_match_config": trigger.get("no_match_config") or {},
            }
            evaluated.append(entry)
            if result["matched"]:
                matched.append(entry)

        selected = matched
        if matched and str(matched[0].get("trigger_policy") or "") == "first_matching":
            selected = [matched[0]]

        return {
            "integration_config_id": integration_config_id,
            "evaluated_trigger_count": len(evaluated),
            "matched_trigger_count": len(matched),
            "selected_trigger_count": len(selected),
            "evaluated_triggers": evaluated,
            "selected_triggers": selected,
            "workflow_run_creation": "pending" if selected else "none",
        }

    def _create_initial_runs_from_trigger_evaluation(
        self,
        *,
        workspace_id: str,
        integration: dict[str, Any],
        intake_event_id: int,
        normalized_payload: dict[str, Any],
        trigger_evaluation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        created_runs = []
        for trigger in trigger_evaluation.get("selected_triggers") or []:
            workflow_version_id = trigger.get("workflow_version_id")
            if workflow_version_id is None:
                created_runs.append(
                    {
                        "trigger_id": trigger.get("id"),
                        "trigger_key": trigger.get("trigger_key"),
                        "status": "skipped",
                        "reason": "workflow_version_unresolved",
                    }
                )
                continue
            idempotency_key = f"intake:{intake_event_id}:trigger:{trigger.get('id')}"
            existing = self._runtime_repository.get_run_by_idempotency(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                created_runs.append(
                    {
                        "run_id": existing.get("id"),
                        "trigger_id": trigger.get("id"),
                        "trigger_key": trigger.get("trigger_key"),
                        "workflow_definition_id": existing.get("workflow_definition_id"),
                        "workflow_version_id": existing.get("workflow_version_id"),
                        "status": existing.get("status"),
                        "idempotency_key": idempotency_key,
                        "created": False,
                    }
                )
                continue
            run_context = {
                "source": "jotform",
                "integration_id": integration.get("id"),
                "integration_key": integration.get("integration_key"),
                "trigger_id": trigger.get("id"),
                "trigger_key": trigger.get("trigger_key"),
                "field_mapping": trigger.get("field_mapping") or {},
                "no_match_config": trigger.get("no_match_config") or {},
                "intake": normalized_payload,
            }
            run_identity = self._workflow_run_identity(
                workspace_id=workspace_id,
                workflow_definition_id=int(trigger["workflow_definition_id"]),
            )
            run_id = self._runtime_repository.create_run(
                workspace_id=workspace_id,
                workflow_definition_id=int(trigger["workflow_definition_id"]),
                workflow_version_id=int(workflow_version_id),
                intake_event_id=intake_event_id,
                mode=str(integration.get("mode") or "production"),
                status="waiting",
                current_node_id="intake",
                idempotency_key=idempotency_key,
                run_context=run_context,
                run_as_principal_type=run_identity["run_as_principal_type"],
                run_as_principal_id=run_identity["run_as_principal_id"],
                triggered_by_user_id=None,
            )
            self._runtime_repository.append_run_event(
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="workflow.run.created",
                node_id="intake",
                message="Workflow run created from integration trigger.",
                event_payload={
                    "intake_event_id": intake_event_id,
                    "trigger_id": trigger.get("id"),
                    "trigger_key": trigger.get("trigger_key"),
                    "workflow_definition_id": trigger.get("workflow_definition_id"),
                    "workflow_version_id": workflow_version_id,
                    "mode": integration.get("mode"),
                    "run_as_principal_type": run_identity["run_as_principal_type"],
                    "run_as_principal_id": run_identity["run_as_principal_id"],
                },
                actor_type="system",
                actor_id="flowforge",
                idempotency_key=f"{idempotency_key}:event:created",
            )
            self._enqueue_created_run_dispatch(
                workspace_id=workspace_id,
                run_id=int(run_id),
                idempotency_key=idempotency_key,
            )
            created_runs.append(
                {
                    "run_id": run_id,
                    "trigger_id": trigger.get("id"),
                    "trigger_key": trigger.get("trigger_key"),
                    "workflow_definition_id": trigger.get("workflow_definition_id"),
                    "workflow_version_id": workflow_version_id,
                    "status": "waiting",
                    "idempotency_key": idempotency_key,
                    "created": True,
                }
            )
        return created_runs

    def _workflow_run_identity(self, *, workspace_id: str, workflow_definition_id: int) -> dict[str, Any]:
        workflow = self._workflow_repository.get_workflow_definition(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        if not workflow:
            return {"run_as_principal_type": None, "run_as_principal_id": None}
        return {
            "run_as_principal_type": str(workflow.get("run_as_principal_type") or "").strip() or None,
            "run_as_principal_id": str(workflow.get("run_as_principal_id") or "").strip() or None,
        }

    def _enqueue_created_run_dispatch(self, *, workspace_id: str, run_id: int, idempotency_key: str) -> None:
        try:
            from app.tasks import flowforge_tasks

            flowforge_tasks.enqueue_flowforge_run_dispatch(workspace_id, run_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "FlowForge run dispatch enqueue failed workspace_id=%s run_id=%s",
                workspace_id,
                run_id,
            )
            self._runtime_repository.append_run_event(
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="workflow.dispatch.enqueue_failed",
                node_id=None,
                message="Workflow run dispatch enqueue failed.",
                event_payload={"error": str(exc)},
                actor_type="system",
                actor_id="flowforge",
                idempotency_key=f"{idempotency_key}:event:dispatch_enqueue_failed",
            )

    def _evaluate_trigger_condition(
        self,
        *,
        trigger_mode: str,
        condition: dict[str, Any],
        normalized_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if trigger_mode == "always":
            return {"matched": True, "reason": "always"}
        checks = self._condition_checks(condition)
        if not checks:
            return {"matched": False, "reason": "empty_condition"}
        failed = []
        for check in checks:
            if str(check.get("operator") or "") == "any" and isinstance(check.get("value"), list):
                if any(
                    self._condition_matches(
                        actual=self._payload_path(normalized_payload, str(candidate.get("field") or "")),
                        operator=str(candidate.get("operator") or "equals"),
                        expected=candidate.get("value"),
                    )
                    for candidate in check["value"]
                    if isinstance(candidate, dict)
                ):
                    continue
                failed.append({"operator": "any", "expected": check.get("value"), "actual": None})
                continue
            field = str(check.get("field") or "").strip()
            operator = str(check.get("operator") or "equals").strip()
            expected = check.get("value")
            actual = self._payload_path(normalized_payload, field)
            if not self._condition_matches(actual=actual, operator=operator, expected=expected):
                failed.append({"field": field, "operator": operator, "expected": expected, "actual": actual})
        if failed:
            return {"matched": False, "reason": "condition_not_matched", "failed": failed}
        return {"matched": True, "reason": "condition_matched"}

    def _condition_checks(self, condition: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(condition.get("all"), list):
            return [row for row in condition["all"] if isinstance(row, dict)]
        if isinstance(condition.get("any"), list):
            checks = [row for row in condition["any"] if isinstance(row, dict)]
            return [{"field": "__any__", "operator": "any", "value": checks}]
        if {"field", "operator", "value"}.issubset(condition.keys()):
            return [condition]
        return [{"field": key, "operator": "equals", "value": value} for key, value in condition.items()]

    def _condition_matches(self, *, actual: Any, operator: str, expected: Any) -> bool:
        if operator == "exists":
            return actual is not None
        if operator == "not_exists":
            return actual is None
        if operator == "equals":
            return actual == expected
        if operator == "not_equals":
            return actual != expected
        if operator == "in" and isinstance(expected, list):
            return actual in expected
        if operator == "contains":
            if isinstance(actual, list):
                return expected in actual
            return str(expected) in str(actual or "")
        return False

    def _payload_path(self, payload: dict[str, Any], path: str) -> Any:
        current: Any = payload
        for part in str(path or "").split("."):
            if not part:
                continue
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

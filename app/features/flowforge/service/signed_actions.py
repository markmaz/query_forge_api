from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeSignedActionServiceMixin:
    def create_signed_action_token(
        self,
        *,
        workspace_id: str,
        human_task_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        task = self._runtime_repository.get_human_task(workspace_id=workspace_id, human_task_id=human_task_id)
        if task is None:
            raise ForgeError(f"FlowForge human task '{human_task_id}' was not found.", status_code=404)

        allowed_actions = self._normalize_allowed_actions((payload or {}).get("allowed_actions"))
        expires_at = self._optional_string((payload or {}).get("expires_at"))
        if not expires_at:
            raise ForgeError("expires_at is required.", status_code=400)

        token = self._generate_signed_action_token()
        token_hash = self._hash_signed_action_token(token)
        self._runtime_repository.create_signed_action_token(
            workspace_id=workspace_id,
            human_task_id=human_task_id,
            token_hash=token_hash,
            allowed_actions=allowed_actions,
            expires_at=expires_at,
        )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=int(task["run_id"]),
            event_type="workflow.signed_action.created",
            node_id=None,
            message="Signed action token created.",
            event_payload={"human_task_id": int(human_task_id), "allowed_actions": allowed_actions},
            actor_type="user",
            actor_id=self._optional_string(actor_user_id),
            idempotency_key=self._optional_string((payload or {}).get("idempotency_key")),
        )
        return {
            "human_task_id": int(human_task_id),
            "token": token,
            "allowed_actions": allowed_actions,
            "expires_at": expires_at,
        }

    def get_signed_action_details(self, *, token: str) -> dict[str, Any]:
        row = self._load_signed_action_token(token=token)
        return {
            "valid": True,
            "allowed_actions": row["allowed_actions_json"],
            "expires_at": row.get("expires_at"),
            "task": self._serialize_public_signed_action_task(row),
        }

    def complete_signed_action(
        self,
        *,
        token: str,
        action: str,
        payload: dict[str, Any],
        source_ip: str | None,
    ) -> dict[str, Any]:
        row = self._load_signed_action_token(token=token)
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"accept", "decline"}:
            raise ForgeError("Unsupported signed action.", status_code=400)
        if normalized_action not in set(row["allowed_actions_json"]):
            raise ForgeError("Signed action is not allowed for this token.", status_code=403)

        task_status = "accepted" if normalized_action == "accept" else "declined"
        response = {
            "action": normalized_action,
            "response_note": self._optional_string((payload or {}).get("response_note")),
            "decline_reason": self._optional_string((payload or {}).get("decline_reason")),
        }
        token_hash = self._hash_signed_action_token(token)
        if not self._runtime_repository.mark_signed_action_token_used(
            token_hash=token_hash,
            used_action=normalized_action,
            used_ip=source_ip,
        ):
            raise ForgeError("Signed action token has already been used or revoked.", status_code=409)
        self._runtime_repository.update_human_task_response(
            workspace_id=row["workspace_id"],
            human_task_id=int(row["human_task_id"]),
            status=task_status,
            response=response,
        )
        self._runtime_repository.append_run_event(
            workspace_id=row["workspace_id"],
            run_id=int(row["run_id"]),
            event_type=f"workflow.human_task.{task_status}",
            node_id=None,
            message=f"Human task {task_status}.",
            event_payload={
                "human_task_id": int(row["human_task_id"]),
                "action": normalized_action,
                "source_record_key": row.get("source_record_key"),
            },
            actor_type="signed_action",
            actor_id=str(row["human_task_id"]),
            idempotency_key=f"signed-action:{token_hash}:{normalized_action}",
        )
        runtime_result = self._advance_after_signed_action(row=row, action=normalized_action)
        return {
            "accepted": True,
            "action": normalized_action,
            "runtime": runtime_result,
            "task": {
                **self._serialize_public_signed_action_task(row),
                "status": task_status,
            },
        }

    def _advance_after_signed_action(self, *, row: dict[str, Any], action: str) -> dict[str, Any]:
        from app.features.flowforge.runtime.human_responses import FlowForgeHumanResponseRuntime

        return FlowForgeHumanResponseRuntime(runtime_repository=self._runtime_repository).advance_after_human_action(
            workspace_id=str(row["workspace_id"]),
            run_id=int(row["run_id"]),
            action=action,
            human_task_id=int(row["human_task_id"]),
            resource_set_id=row.get("resource_set_id"),
            source_record_key=row.get("source_record_key"),
        )

    def _serialize_public_signed_action_task(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_type": row.get("task_type"),
            "status": row.get("task_status"),
            "source_record_key": row.get("source_record_key"),
        }

    def _normalize_allowed_actions(self, raw: Any) -> list[str]:
        if not isinstance(raw, list):
            raise ForgeError("allowed_actions must be an array.", status_code=400)
        allowed = [str(value or "").strip().lower() for value in raw]
        allowed = [value for value in allowed if value]
        if not allowed:
            raise ForgeError("allowed_actions is required.", status_code=400)
        unsupported = sorted(set(allowed) - {"accept", "decline"})
        if unsupported:
            raise ForgeError(f"Unsupported allowed_actions: {', '.join(unsupported)}.", status_code=400)
        return allowed

    def _load_signed_action_token(self, *, token: str) -> dict[str, Any]:
        token_hash = self._hash_signed_action_token(token)
        row = self._runtime_repository.get_signed_action_token(token_hash=token_hash)
        if row is None:
            raise ForgeError("Signed action token was not found.", status_code=404)
        if row.get("used_at") or row.get("revoked_at"):
            raise ForgeError("Signed action token has already been used or revoked.", status_code=409)
        if self._is_expired(row.get("expires_at")):
            raise ForgeError("Signed action token has expired.", status_code=410)
        if str(row.get("task_status") or "") not in {"pending", "waiting"}:
            raise ForgeError("Human task is no longer pending.", status_code=409)
        return row

    def _generate_signed_action_token(self) -> str:
        return f"ffact_{secrets.token_urlsafe(32)}"

    def _hash_signed_action_token(self, token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _is_expired(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, datetime):
            expires_at = value
        else:
            text = str(value).strip().replace("Z", "+00:00")
            try:
                expires_at = datetime.fromisoformat(text)
            except ValueError:
                return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC)

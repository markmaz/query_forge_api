from __future__ import annotations

from typing import Any

from app.config.llm_resolver import ResolvedLLMRuntime
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.llm_drafting import MatchingPolicyDraftGenerator, normalize_generated_matching_policy


class FlowForgeMatchingPolicyServiceMixin:
    def validate_matching_policy(self, *, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        del workspace_id
        policy = payload.get("policy") if isinstance(payload, dict) else None
        if not isinstance(policy, dict):
            raise ForgeError("policy must be an object.", status_code=400)
        result = self._matching_engine.validate_policy(policy)
        return {
            "valid": result["valid"],
            "errors": result["errors"],
            "warnings": result["warnings"],
            "policy": policy,
        }

    def simulate_matching_policy(self, *, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        del workspace_id
        policy = payload.get("policy") if isinstance(payload, dict) else None
        resources = payload.get("resources") if isinstance(payload, dict) else None
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(policy, dict):
            raise ForgeError("policy must be an object.", status_code=400)
        if not isinstance(resources, list):
            raise ForgeError("resources must be an array for stateless simulation.", status_code=400)
        if not isinstance(context, dict):
            raise ForgeError("context must be an object.", status_code=400)
        return self._matching_engine.simulate(policy=policy, resources=[row for row in resources if isinstance(row, dict)], context=context)

    def list_matching_policies(self, *, workspace_id: str) -> list[dict[str, Any]]:
        return [self._serialize_matching_policy(row) for row in self._matching_repository.list_policies(workspace_id=workspace_id)]

    def get_matching_policy(self, *, workspace_id: str, matching_policy_id: int) -> dict[str, Any] | None:
        row = self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=matching_policy_id)
        if row is None:
            return None
        return self._serialize_matching_policy(row)

    def delete_matching_policy(self, *, workspace_id: str, matching_policy_id: int, actor_user_id: str) -> dict[str, Any]:
        policy = self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=matching_policy_id)
        if policy is None:
            raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
        versions = self._matching_repository.list_policy_versions(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
        )
        if any(str(version.get("version_status") or "").strip() == "published" for version in versions):
            raise ForgeError("Matching policies with published versions cannot be deleted.", status_code=400)
        updated_by = str(actor_user_id or "").strip() or None
        archived = self._matching_repository.archive_policy(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            updated_by=updated_by,
        )
        if not archived:
            raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
        deleted_versions = self._matching_repository.delete_non_published_policy_versions(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            updated_by=updated_by,
        )
        return {
            "deleted": True,
            "matching_policy_id": matching_policy_id,
            "deleted_versions": deleted_versions,
        }

    def create_matching_policy(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        policy_key = str(payload.get("policy_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        resource_set_id = payload.get("resource_set_id")
        if not policy_key:
            raise ForgeError("policy_key is required.", status_code=400)
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)
        if resource_set_id is None:
            raise ForgeError("resource_set_id is required.", status_code=400)
        policy_json = payload.get("policy")
        if policy_json is not None and not isinstance(policy_json, dict):
            raise ForgeError("policy must be an object when supplied.", status_code=400)
        created = self._matching_repository.create_policy(
            workspace_id=workspace_id,
            policy_key=policy_key,
            display_name=display_name,
            description=str(payload.get("description")).strip() if payload.get("description") is not None else None,
            resource_set_id=int(resource_set_id),
            created_by=str(actor_user_id or "").strip() or None,
        )
        serialized = self._serialize_matching_policy(created)
        if isinstance(policy_json, dict):
            version = self.create_matching_policy_version(
                workspace_id=workspace_id,
                matching_policy_id=int(serialized["id"]),
                payload={"policy": policy_json},
                actor_user_id=actor_user_id,
            )
            serialized["current_draft_version_id"] = version["id"]
        return serialized

    def list_matching_policy_versions(self, *, workspace_id: str, matching_policy_id: int) -> list[dict[str, Any]]:
        if self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=matching_policy_id) is None:
            raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
        return [
            self._serialize_matching_policy_version(row)
            for row in self._matching_repository.list_policy_versions(
                workspace_id=workspace_id,
                matching_policy_id=matching_policy_id,
            )
        ]

    def create_matching_policy_version(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        policy = self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=matching_policy_id)
        if policy is None:
            raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
        policy_json = payload.get("policy") if isinstance(payload, dict) else None
        if not isinstance(policy_json, dict):
            raise ForgeError("policy must be an object.", status_code=400)
        validation = self._matching_engine.validate_policy(policy_json)
        if not validation["valid"]:
            raise ForgeError(
                "Matching policy is invalid.",
                status_code=400,
                details={"errors": validation["errors"], "warnings": validation["warnings"]},
            )
        existing_versions = self._matching_repository.list_policy_versions(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
        )
        next_version_number = max([int(row.get("version_number") or 0) for row in existing_versions] or [0]) + 1
        version_id = self._matching_repository.create_policy_version(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            resource_set_id=int(policy["resource_set_id"]),
            version_number=next_version_number,
            policy=policy_json,
            created_by=str(actor_user_id or "").strip() or None,
            version_status="draft",
            validation_status="valid",
            validation_result={"errors": validation["errors"], "warnings": validation["warnings"]},
        )
        self._matching_repository.set_current_draft_version(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            matching_policy_version_id=version_id,
            updated_by=str(actor_user_id or "").strip() or None,
        )
        return {
            "id": version_id,
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "resource_set_id": int(policy["resource_set_id"]),
            "version_number": next_version_number,
            "version_status": "draft",
            "policy": policy_json,
            "validation_status": "valid",
            "validation_result": {"errors": validation["errors"], "warnings": validation["warnings"]},
        }

    def delete_matching_policy_version(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        matching_policy_version_id: int,
        actor_user_id: str,
    ) -> dict[str, Any]:
        policy = self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=matching_policy_id)
        if policy is None:
            raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
        version = self._matching_repository.get_policy_version(
            workspace_id=workspace_id,
            version_id=matching_policy_version_id,
        )
        if version is None or int(version.get("matching_policy_id") or 0) != int(matching_policy_id):
            raise ForgeError(f"Matching policy version '{matching_policy_version_id}' was not found.", status_code=404)
        version_status = str(version.get("version_status") or "").strip()
        if version_status == "published":
            raise ForgeError("Published matching policy versions cannot be deleted.", status_code=400)
        deleted = self._matching_repository.delete_policy_version(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            matching_policy_version_id=matching_policy_version_id,
            updated_by=str(actor_user_id or "").strip() or None,
        )
        if not deleted:
            raise ForgeError(f"Matching policy version '{matching_policy_version_id}' was not found.", status_code=404)
        self._matching_repository.clear_current_draft_version(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            matching_policy_version_id=matching_policy_version_id,
            updated_by=str(actor_user_id or "").strip() or None,
        )
        return {
            "deleted": True,
            "matching_policy_id": matching_policy_id,
            "matching_policy_version_id": matching_policy_version_id,
        }

    def list_matching_policy_llm_drafts(self, *, workspace_id: str, matching_policy_id: int) -> list[dict[str, Any]]:
        if self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=matching_policy_id) is None:
            raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
        return [
            self._serialize_matching_policy_llm_draft(row)
            for row in self._matching_repository.list_llm_drafts(
                workspace_id=workspace_id,
                matching_policy_id=matching_policy_id,
            )
        ]

    def create_matching_policy_llm_draft(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        policy = self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=matching_policy_id)
        if policy is None:
            raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ForgeError("prompt is required.", status_code=400)
        use_llm = bool(payload.get("use_llm"))
        generator = self._matching_policy_draft_generator
        runtime: ResolvedLLMRuntime | None = None
        if use_llm:
            runtime = self._llm_runtime_builder(
                workspace_id=workspace_id,
                role=LLMRole.FLOWFORGE_RULE_DRAFTING,
            )
            generator = MatchingPolicyDraftGenerator(llm_client=runtime.client)
        generated = generator.generate(
            prompt=prompt,
            resource_set_id=int(policy["resource_set_id"]),
            resource_fields=payload.get("resource_fields") if isinstance(payload.get("resource_fields"), list) else [],
            context_fields=payload.get("context_fields") if isinstance(payload.get("context_fields"), list) else [],
            intake_source=payload.get("intake_source") if isinstance(payload.get("intake_source"), dict) else None,
            intake_fields=payload.get("intake_fields") if isinstance(payload.get("intake_fields"), list) else [],
            use_llm=use_llm,
        )
        generated_policy = generated.get("generated_policy") if isinstance(generated.get("generated_policy"), dict) else {}
        generated_policy = normalize_generated_matching_policy(generated_policy, resource_set_id=int(policy["resource_set_id"]))
        validation = self._matching_engine.validate_policy(generated_policy)
        saved = self._matching_repository.create_llm_draft(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            resource_set_id=int(policy["resource_set_id"]),
            prompt=prompt,
            generated_policy=generated_policy,
            plain_language_summary=self._optional_string(generated.get("plain_language_summary")),
            validation_status="valid" if validation["valid"] else "invalid",
            validation_result={"errors": validation["errors"], "warnings": validation["warnings"]},
            model_provider=self._optional_string(runtime.provider if runtime is not None else generated.get("model_provider")),
            model_name=self._optional_string(runtime.model if runtime is not None else generated.get("model_name")),
            status="drafted",
            created_by=str(actor_user_id or "").strip() or None,
        )
        serialized = self._serialize_matching_policy_llm_draft(saved)
        serialized["draft_source"] = generated.get("draft_source")
        return serialized

    def accept_matching_policy_llm_draft(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        draft_id: int,
        actor_user_id: str,
    ) -> dict[str, Any]:
        draft = self._matching_repository.get_llm_draft(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            draft_id=draft_id,
        )
        if draft is None:
            raise ForgeError(f"Matching policy LLM draft '{draft_id}' was not found.", status_code=404)
        generated_policy = draft.get("generated_policy_json")
        if not isinstance(generated_policy, dict):
            raise ForgeError("Matching policy LLM draft does not contain generated policy JSON.", status_code=400)
        generated_policy = normalize_generated_matching_policy(generated_policy)
        validation = self._matching_engine.validate_policy(generated_policy)
        if not validation["valid"]:
            raise ForgeError(
                "Matching policy LLM draft is invalid and cannot be accepted.",
                status_code=400,
                details={"errors": validation["errors"], "warnings": validation["warnings"]},
            )
        version = self.create_matching_policy_version(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            payload={"policy": generated_policy},
            actor_user_id=actor_user_id,
        )
        self._matching_repository.mark_llm_draft_reviewed(
            workspace_id=workspace_id,
            matching_policy_id=matching_policy_id,
            draft_id=draft_id,
            status="accepted",
            reviewed_by=str(actor_user_id or "").strip() or None,
        )
        accepted_draft = self._serialize_matching_policy_llm_draft({**draft, "status": "accepted"})
        return {"draft": accepted_draft, "version": version}

    def _serialize_matching_policy(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "policy_key": row.get("policy_key"),
            "display_name": row.get("display_name"),
            "description": row.get("description"),
            "resource_set_id": row.get("resource_set_id"),
            "status": row.get("status"),
            "current_draft_version_id": row.get("current_draft_version_id"),
            "latest_published_version_id": row.get("latest_published_version_id"),
        }

    def _serialize_matching_policy_version(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "matching_policy_id": row.get("matching_policy_id"),
            "resource_set_id": row.get("resource_set_id"),
            "version_number": row.get("version_number"),
            "version_status": row.get("version_status"),
            "policy": row.get("policy") or row.get("policy_json") or {},
            "validation_status": row.get("validation_status"),
            "validation_result": row.get("validation_result") or row.get("validation_result_json") or {},
            "created_at": row.get("created_at"),
            "published_at": row.get("published_at"),
        }

    def _serialize_matching_policy_llm_draft(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "matching_policy_id": row.get("matching_policy_id"),
            "resource_set_id": row.get("resource_set_id"),
            "prompt": row.get("prompt"),
            "generated_policy": row.get("generated_policy") or row.get("generated_policy_json") or {},
            "plain_language_summary": row.get("plain_language_summary"),
            "validation_status": row.get("validation_status"),
            "validation_result": row.get("validation_result") or row.get("validation_result_json") or {},
            "model_provider": row.get("model_provider"),
            "model_name": row.get("model_name"),
            "status": row.get("status"),
            "created_at": row.get("created_at"),
            "reviewed_at": row.get("reviewed_at"),
        }

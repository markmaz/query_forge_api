from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.constants.llm_roles import LLMProvider, LLMRole
from app.ports.sql_executor import ForgeQueryPort
from app.utils.encryption import decrypt_api_key, encrypt_api_key, mask_api_key

logger = logging.getLogger(__name__)

_VALID_ROLES = set(LLMRole.ALL)
_VALID_PROVIDERS = set(LLMProvider.ALL)

_SELECT_COLS = """
    id, workspace_id, name, provider, model_name, role,
    api_key_encrypted, endpoint_url, is_active, config_json,
    created_at, updated_at
"""


class WorkspaceLLMService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_all_for_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        ws = str(workspace_id or "").strip()
        if not ws:
            return []
        try:
            rows = self._sql.execute_query_mappings(
                f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE workspace_id = :ws ORDER BY role, id",
                {"ws": ws},
            )
        except Exception:
            logger.exception("get_all_for_workspace failed for %s", ws)
            return []
        return [self._to_public_dict(row) for row in rows]

    def get_by_id(self, llm_id: int) -> Optional[Dict[str, Any]]:
        try:
            rows = self._sql.execute_query_mappings(
                f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
                {"id": llm_id},
            )
        except Exception:
            logger.exception("get_by_id failed for id=%s", llm_id)
            return None
        if not rows:
            return None
        return self._to_public_dict(rows[0])

    def get_llm_for_role(self, workspace_id: str, role: str) -> Optional[Dict[str, Any]]:
        ws = str(workspace_id or "").strip()
        r = str(role or "").strip()
        if not ws or not r:
            return None
        try:
            rows = self._sql.execute_query_mappings(
                f"""
                SELECT {_SELECT_COLS} FROM workspace_llm
                WHERE workspace_id = :ws AND role = :role AND is_active = 1
                LIMIT 1
                """,
                {"ws": ws, "role": r},
            )
        except Exception:
            logger.exception("get_llm_for_role DB lookup failed ws=%s role=%s", ws, r)
            rows = []
        if rows:
            return self._to_internal_dict(rows[0])
        return self._env_fallback(r)

    def create_llm(self, workspace_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip()
        role = str(data.get("role") or "").strip()
        provider = str(data.get("provider") or "").strip()
        name = str(data.get("name") or "").strip()
        model_name = str(data.get("model_name") or "").strip()
        is_active = bool(data.get("is_active", True))

        if not ws:
            raise ValueError("workspace_id is required")
        if not name:
            raise ValueError("name is required")
        if role not in _VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {sorted(_VALID_ROLES)}")
        if provider not in _VALID_PROVIDERS:
            raise ValueError(f"Invalid provider '{provider}'. Must be one of: {sorted(_VALID_PROVIDERS)}")
        if not model_name:
            raise ValueError("model_name is required")

        if is_active:
            self._assert_no_active_for_role(ws, role, exclude_id=None)

        api_key_plaintext = str(data.get("api_key") or "").strip() or None
        api_key_encrypted = encrypt_api_key(api_key_plaintext) if api_key_plaintext else None
        endpoint_url = str(data.get("endpoint_url") or "").strip() or None
        config_json_raw = data.get("config_json")
        config_json = json.dumps(config_json_raw) if config_json_raw else None

        self._sql.execute_write(
            """
            INSERT INTO workspace_llm
              (workspace_id, name, provider, model_name, role,
               api_key_encrypted, endpoint_url, is_active, config_json)
            VALUES
              (:ws, :name, :provider, :model_name, :role,
               :api_key_encrypted, :endpoint_url, :is_active, :config_json)
            """,
            {
                "ws": ws, "name": name, "provider": provider, "model_name": model_name,
                "role": role, "api_key_encrypted": api_key_encrypted,
                "endpoint_url": endpoint_url, "is_active": 1 if is_active else 0,
                "config_json": config_json,
            },
        )

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT {_SELECT_COLS} FROM workspace_llm
            WHERE workspace_id = :ws AND name = :name AND role = :role
            ORDER BY id DESC LIMIT 1
            """,
            {"ws": ws, "name": name, "role": role},
        )
        if not rows:
            raise RuntimeError("Failed to fetch newly created workspace_llm")
        return self._to_public_dict(rows[0])

    def update_llm(self, llm_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        existing_rows = self._sql.execute_query_mappings(
            f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
            {"id": llm_id},
        )
        if not existing_rows:
            raise ValueError(f"workspace_llm id={llm_id} not found")
        existing = dict(existing_rows[0])
        ws = existing["workspace_id"]

        name = str(data.get("name") or existing.get("name") or "").strip()
        provider = str(data.get("provider") or existing.get("provider") or "").strip()
        model_name = str(data.get("model_name") or existing.get("model_name") or "").strip()
        role = str(data.get("role") or existing.get("role") or "").strip()
        is_active = bool(data.get("is_active", bool(int(existing.get("is_active") or 1))))
        endpoint_url = str(data.get("endpoint_url") or existing.get("endpoint_url") or "").strip() or None

        if role not in _VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'")
        if provider not in _VALID_PROVIDERS:
            raise ValueError(f"Invalid provider '{provider}'")

        if is_active:
            self._assert_no_active_for_role(ws, role, exclude_id=llm_id)

        api_key_plaintext = str(data.get("api_key") or "").strip() or None
        api_key_encrypted = encrypt_api_key(api_key_plaintext) if api_key_plaintext else existing.get("api_key_encrypted")

        config_json_raw = data.get("config_json")
        config_json = json.dumps(config_json_raw) if config_json_raw is not None else existing.get("config_json")

        self._sql.execute_write(
            """
            UPDATE workspace_llm SET
              name = :name, provider = :provider, model_name = :model_name,
              role = :role, api_key_encrypted = :api_key_encrypted,
              endpoint_url = :endpoint_url, is_active = :is_active,
              config_json = :config_json
            WHERE id = :id
            """,
            {
                "name": name, "provider": provider, "model_name": model_name,
                "role": role, "api_key_encrypted": api_key_encrypted,
                "endpoint_url": endpoint_url, "is_active": 1 if is_active else 0,
                "config_json": config_json, "id": llm_id,
            },
        )

        updated = self._sql.execute_query_mappings(
            f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
            {"id": llm_id},
        )
        if not updated:
            raise RuntimeError(f"Failed to fetch updated workspace_llm id={llm_id}")
        return self._to_public_dict(updated[0])

    def delete_llm(self, llm_id: int) -> None:
        self._sql.execute_write(
            "DELETE FROM workspace_llm WHERE id = :id",
            {"id": llm_id},
        )

    def test_connection(self, llm_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
            {"id": llm_id},
        )
        if not rows:
            return {"success": False, "message": f"LLM config id={llm_id} not found"}
        config = self._to_internal_dict(rows[0])
        provider = config.get("provider")
        endpoint = config.get("endpoint_url") or ""
        api_key = config.get("api_key") or ""
        model = config.get("model_name") or ""
        try:
            if provider in (LLMProvider.OLLAMA, LLMProvider.GENERIC):
                return self._test_openai_compatible(endpoint, api_key, model)
            elif provider == LLMProvider.OPENAI:
                return self._test_openai_compatible("https://api.openai.com/v1", api_key, model)
            elif provider == LLMProvider.ANTHROPIC:
                return self._test_anthropic(api_key, model)
            elif provider == LLMProvider.AZURE_OPENAI:
                return self._test_openai_compatible(endpoint, api_key, model)
            else:
                return {"success": False, "message": f"Unknown provider: {provider}"}
        except Exception as exc:
            logger.exception("test_connection failed for llm_id=%s", llm_id)
            return {"success": False, "message": str(exc)}

    # ── helpers ───────────────────────────────────────────────────────────────

    def _assert_no_active_for_role(self, workspace_id: str, role: str, *, exclude_id: Optional[int]) -> None:
        sql = """
            SELECT id FROM workspace_llm
            WHERE workspace_id = :ws AND role = :role AND is_active = 1
        """
        params: Dict[str, Any] = {"ws": workspace_id, "role": role}
        if exclude_id is not None:
            sql += " AND id != :exclude_id"
            params["exclude_id"] = exclude_id
        sql += " LIMIT 1"
        rows = self._sql.execute_query_mappings(sql, params)
        if rows:
            raise ValueError(
                f"Workspace '{workspace_id}' already has an active LLM for role '{role}'. "
                "Deactivate it first."
            )

    def _to_public_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        encrypted = row.get("api_key_encrypted")
        has_api_key = bool(encrypted)
        masked = None
        if has_api_key:
            try:
                plaintext = decrypt_api_key(encrypted)
                masked = mask_api_key(plaintext) if plaintext else None
            except Exception:
                masked = "****"
        config_json = self._coerce_json(row.get("config_json"))
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "name": row.get("name"),
            "provider": row.get("provider"),
            "model_name": row.get("model_name"),
            "role": row.get("role"),
            "has_api_key": has_api_key,
            "masked_api_key": masked,
            "endpoint_url": row.get("endpoint_url"),
            "is_active": bool(int(row.get("is_active") or 0)),
            "config_json": config_json,
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        }

    def _to_internal_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        encrypted = row.get("api_key_encrypted")
        api_key = decrypt_api_key(encrypted) if encrypted else None
        config_json = self._coerce_json(row.get("config_json"))
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "provider": row.get("provider"),
            "model_name": row.get("model_name"),
            "role": row.get("role"),
            "api_key": api_key,
            "endpoint_url": row.get("endpoint_url"),
            "is_active": bool(int(row.get("is_active") or 0)),
            "config_json": config_json,
        }

    def _env_fallback(self, role: str) -> Optional[Dict[str, Any]]:
        vllm_url = os.getenv("VLLM_BASE_URL", "").strip()
        vllm_model = os.getenv("VLLM_MODEL", "").strip()
        if role in (LLMRole.PLANNER, LLMRole.QUERY_GENERATOR, LLMRole.ENRICHMENT):
            endpoint = vllm_url
            model = os.getenv("SEMANTIC_PLAN_LLM_MODEL", vllm_model).strip() or vllm_model
        elif role in (LLMRole.NER, LLMRole.SUMMARIZER):
            endpoint = os.getenv("SEMANTIC_LLM_ENDPOINT", vllm_url).strip()
            model = os.getenv("SEMANTIC_LLM_MODEL", vllm_model).strip() or vllm_model
        else:
            endpoint = vllm_url
            model = vllm_model
        if not endpoint or not model:
            return None
        return {
            "provider": LLMProvider.GENERIC,
            "model_name": model,
            "role": role,
            "api_key": None,
            "endpoint_url": endpoint,
            "is_active": True,
            "config_json": None,
            "_source": "env",
        }

    @staticmethod
    def _coerce_json(value: Any) -> Optional[Dict[str, Any]]:
        if isinstance(value, dict):
            return value
        if not value:
            return None
        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _test_openai_compatible(self, endpoint: str, api_key: str, model: str) -> Dict[str, Any]:
        import httpx
        url = endpoint.rstrip("/") + "/models"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            r = httpx.get(url, headers=headers, timeout=10)
            if r.status_code < 400:
                return {"success": True, "message": f"Connected to {endpoint} (HTTP {r.status_code})"}
            return {"success": False, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def _test_anthropic(self, api_key: str, model: str) -> Dict[str, Any]:
        import httpx
        try:
            r = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key or "", "anthropic-version": "2023-06-01"},
                timeout=10,
            )
            if r.status_code < 400:
                return {"success": True, "message": f"Anthropic API reachable (HTTP {r.status_code})"}
            return {"success": False, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

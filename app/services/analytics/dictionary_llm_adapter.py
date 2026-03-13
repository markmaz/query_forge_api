from __future__ import annotations

import json
from typing import Any, Sequence

from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.services.llm.llm_client import LLMClient


class DictionaryLLMAdapter:
    """Adapter exposing a simple ``generate(prompt)`` API for dictionary enrichment."""

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        workspace_id: str | None = None,
        llm_id: int | None = None,
    ) -> None:
        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient()
        if workspace_id and not self._explicit_llm:
            self._resolve_runtime_llm(workspace_id=workspace_id, llm_id_override=llm_id)

    def _resolve_runtime_llm(self, *, workspace_id: str, llm_id_override: int | None = None) -> None:
        resolved = build_llm_client_for_role(
            workspace_id=str(workspace_id or "").strip(),
            role=LLMRole.ENRICHMENT,
            llm_id_override=llm_id_override,
            timeout_seconds=None,
        )
        self._llm = resolved.client

    def generate(self, prompt: str, *, workspace_id: str | None = None, llm_id: int | None = None) -> str:
        if workspace_id and not self._explicit_llm:
            self._resolve_runtime_llm(workspace_id=workspace_id, llm_id_override=llm_id)
        payload: dict[str, Any] = self._llm.chat_json(
            system_prompt=(
                "You write concise data dictionary descriptions for analytics columns. "
                "Return strict JSON with key 'description' only."
            ),
            user_prompt=prompt,
            response_format=True,
            retry_invalid_schema=True,
            validator=lambda d: isinstance(d.get("description"), str) and bool(str(d.get("description")).strip()),
            max_tokens=120,
        )
        return str(payload.get("description") or "").strip()

    def generate_table_description(
        self,
        *,
        table_name: str,
        columns: Sequence[dict[str, Any]],
        workspace_id: str | None = None,
        llm_id: int | None = None,
    ) -> str:
        if workspace_id and not self._explicit_llm:
            self._resolve_runtime_llm(workspace_id=workspace_id, llm_id_override=llm_id)
        compact_columns = [
            {
                "column_name": str(col.get("column_name") or "").strip(),
                "data_type": str(col.get("data_type") or "").strip() or "unknown",
                "description": str(col.get("description") or "").strip() or None,
            }
            for col in columns
            if str(col.get("column_name") or "").strip()
        ]
        payload: dict[str, Any] = self._llm.chat_json(
            system_prompt=(
                "You write concise, practical data dictionary descriptions for analytics tables. "
                "Infer business purpose from columns and their descriptions. "
                "Return strict JSON with key 'description' only."
            ),
            user_prompt=(
                f"Write a concise one-sentence description for table '{table_name}'. "
                "Use this column context:\n"
                f"{json.dumps(compact_columns, ensure_ascii=False)}"
            ),
            response_format=True,
            retry_invalid_schema=True,
            validator=lambda d: isinstance(d.get("description"), str) and bool(str(d.get("description")).strip()),
            max_tokens=180,
        )
        return str(payload.get("description") or "").strip()

    def generate_column_metadata(
        self,
        *,
        table_name: str,
        table_description: str | None,
        column_name: str,
        data_type: str | None,
        source_comment: str | None,
        workspace_id: str | None = None,
        llm_id: int | None = None,
    ) -> dict[str, Any]:
        if workspace_id and not self._explicit_llm:
            self._resolve_runtime_llm(workspace_id=workspace_id, llm_id_override=llm_id)
        payload: dict[str, Any] = self._llm.chat_json(
            system_prompt=(
                "You generate column dictionary metadata for analytics modeling and vector retrieval. "
                "Return strict JSON with keys: "
                "description (string), "
                "semantic_type (string), "
                "semantic_entity (string|null), "
                "semantic_sub_type (string|null), "
                "semantic_confidence (number 0-1), "
                "semantic_reasons (array of short strings). "
                "Use semantic_type patterns like: "
                "identifier.student_id, metric.count, attribute.student.race, "
                "time.school_year, geography.city, flag.active, reference.code, other."
            ),
            user_prompt=(
                f"Table: {table_name}\n"
                f"Table description: {table_description or 'none'}\n"
                f"Column: {column_name}\n"
                f"Data type: {data_type or 'unknown'}\n"
                f"Source comment: {source_comment or 'none'}\n"
                "Generate metadata for search and semantic retrieval."
            ),
            response_format=True,
            retry_invalid_schema=True,
            validator=_is_valid_column_payload,
            max_tokens=220,
        )
        return {
            "description": str(payload.get("description") or "").strip() or None,
            "semantic_type": str(payload.get("semantic_type") or "").strip().lower() or None,
            "semantic_entity": str(payload.get("semantic_entity") or "").strip().lower() or None,
            "semantic_sub_type": str(payload.get("semantic_sub_type") or "").strip().lower() or None,
            "semantic_confidence": _clamp_confidence(payload.get("semantic_confidence")),
            "semantic_reasons": _as_string_list(payload.get("semantic_reasons")),
        }


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text[:120])
    return out[:10]


def _clamp_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def _is_valid_column_payload(payload: dict[str, Any]) -> bool:
    description = str(payload.get("description") or "").strip()
    semantic_type = str(payload.get("semantic_type") or "").strip()
    if not description or not semantic_type:
        return False
    confidence = _clamp_confidence(payload.get("semantic_confidence"))
    if confidence is None:
        return False
    return True

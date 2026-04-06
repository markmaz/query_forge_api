from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Optional

from app.exceptions.forge_error import ForgeError
from app.services.forge_match.export_service import ForgeMatchExportService
from app.services.forge_match.session_reader import ForgeMatchSessionReader
from app.services.forge_match.view_draft_sql import (
    ForgeMatchViewDraftBuilder,
    classify_draft_sql_statement,
    normalize_optional_sql_identifier,
    prepare_draft_execution_sql,
)

EXECUTION_WRAP_ERRORS = (OSError, RuntimeError, TypeError, ValueError, KeyError)


class ForgeMatchArtifactService:
    def __init__(
        self,
        *,
        session_reader: ForgeMatchSessionReader,
        view_draft_builder: ForgeMatchViewDraftBuilder,
        exporter: ForgeMatchExportService,
        workspace_context_builder_factory: Callable[[], Any],
    ) -> None:
        self._session_reader = session_reader
        self._view_draft_builder = view_draft_builder
        self._exporter = exporter
        self._workspace_context_builder_factory = workspace_context_builder_factory

    def export_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        export_format: str,
    ) -> tuple[bytes, str, str]:
        return self._exporter.export_session(
            workspace_id=workspace_id,
            session_id=session_id,
            export_format=export_format,
        )

    def create_view_draft(
        self,
        *,
        workspace_id: str,
        session_id: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._session_reader.get_session_row(workspace_id=workspace_id, session_id=session_id)
        accepted = self._session_reader.accepted_columns(workspace_id=workspace_id, session_id=session_id)
        artifact_id = f"fmdv_{uuid.uuid4().hex[:16]}"
        draft_name = (name or f"ForgeMatch View Draft {session_id[:8]}").strip()
        sql_preview = self._view_draft_builder.build_view_draft_sql_preview(
            workspace_id=workspace_id,
            session_id=session_id,
            draft_name=draft_name,
            accepted_columns=accepted,
        )
        return {
            "artifact_id": artifact_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "name": draft_name,
            "accepted_column_count": len(accepted),
            "columns": accepted,
            "status": "draft_created",
            "note": (
                "SQL preview included when the accepted mappings resolve to an executable table/join plan. "
                "No SQL view was created."
            ),
            **sql_preview,
        }

    def execute_view_draft_sql(
        self,
        *,
        workspace_id: str,
        session_id: str,
        sql: str,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._session_reader.get_session_row(workspace_id=workspace_id, session_id=session_id)

        statement_type = classify_draft_sql_statement(sql)
        catalog = normalize_optional_sql_identifier(catalog_name, field="catalog_name")
        schema = normalize_optional_sql_identifier(schema_name, field="schema_name")
        effective_sql = prepare_draft_execution_sql(
            sql,
            catalog_name=catalog,
            schema_name=schema,
        )

        ctx = self._workspace_context_builder_factory().build(workspace_id)
        try:
            result = ctx.sql_exec.submit_statement(
                effective_sql,
                qf_result_fmt="ARROW_STREAM",
            )
        except ForgeError:
            raise
        except EXECUTION_WRAP_ERRORS as exc:
            raise ForgeError(f"Draft SQL execution failed: {str(exc)}", status_code=500) from exc

        status_payload = dict(result.get("status") or {})
        status = str(status_payload.get("state") or "SUCCEEDED").upper()
        rows = result.get("rows") if statement_type == "select" else []
        if not isinstance(rows, list):
            rows = []

        return {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "statement_type": statement_type,
            "status": status,
            "catalog_name": catalog,
            "schema_name": schema,
            "effective_sql": effective_sql,
            "row_count": len(rows),
            "rows": rows[:200],
            "message": (
                "SQL executed successfully."
                if statement_type == "select"
                else "View statement executed successfully."
            ),
        }

    def create_domain_draft(
        self,
        *,
        workspace_id: str,
        session_id: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        accepted = self._session_reader.accepted_columns(workspace_id=workspace_id, session_id=session_id)
        artifact_id = f"fmdd_{uuid.uuid4().hex[:16]}"
        return {
            "artifact_id": artifact_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "name": (name or f"ForgeMatch Domain Draft {session_id[:8]}").strip(),
            "accepted_column_count": len(accepted),
            "columns": accepted,
            "status": "draft_created",
            "note": "V1 draft artifact only; no production domain was created.",
        }


__all__ = ["ForgeMatchArtifactService"]

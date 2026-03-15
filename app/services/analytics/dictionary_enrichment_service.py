# app/services/analytics/dictionary_enrichment_service.py
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.adapters.mysql_sql_executor import ForgeMetaSQL

logger = logging.getLogger(__name__)


class DictionaryEnrichmentService:
    """Optionally generates AI descriptions for workspace_column rows.

    Only fills description when NULL unless overwrite=True.
    All LLM failures are swallowed and logged — never propagated.
    """

    def __init__(
        self,
        *,
        mysql: ForgeMetaSQL | None = None,
        llm=None,
    ) -> None:
        self._mysql = mysql or ForgeMetaSQL()
        self._llm = llm  # any object with .generate(prompt: str) -> str

    def enrich(
        self,
        *,
        table_id_by_name: dict[str, int],
        columns: list[dict],
        overwrite: bool = False,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        workspace_id: str | None = None,
        llm_id: int | None = None,
    ) -> dict[str, Any]:
        """Generate descriptions for columns with missing descriptions.

        :param table_id_by_name: Maps table name -> workspace_table.id (values optional, keys used)
        :param columns: Column dicts with at minimum table_name, column_name, data_type, comment
        :param overwrite: If True, overwrite existing non-null descriptions
        :returns: {enriched: int, errors: int}
        """
        if not self._llm:
            return {"enriched": 0, "errors": 0}

        columns_enriched = 0
        tables_enriched = 0
        errors = 0
        columns_done = 0
        columns_failed = 0
        tables_done = 0
        tables_failed = 0

        # Group columns by table
        cols_by_table: dict[str, list[dict]] = {}
        for col in columns:
            cols_by_table.setdefault(col["table_name"], []).append(col)

        table_state_by_name: dict[str, dict[str, Any]] = {}
        candidate_tables = sorted({str(t or "").strip() for t in table_id_by_name.keys() if str(t or "").strip()})
        if not candidate_tables:
            candidate_tables = sorted(cols_by_table.keys())

        for table_name in candidate_tables:
            table_cols = cols_by_table.get(table_name, [])
            if not table_cols:
                continue

            col_names = sorted({str(c.get("column_name") or "").strip() for c in table_cols if str(c.get("column_name") or "").strip()})
            if not col_names:
                continue

            placeholders = ", ".join(f":c{i}" for i in range(len(col_names)))
            with self._mysql.transaction() as tx:
                existing_columns = tx.execute_query_mappings(
                    f"""
SELECT
  MIN(wc.id) AS id,
  wc.column_name,
  MAX(wc.description) AS description,
  MAX(wc.semantic_type) AS semantic_type,
  MAX(wc.semantic_entity) AS semantic_entity,
  MAX(wc.semantic_sub_type) AS semantic_sub_type
FROM workspace_column wc
JOIN workspace_table wt
  ON wt.id = wc.workspace_table_id
WHERE wt.table_name = :table_name
  AND wc.column_name IN ({placeholders})
GROUP BY wc.column_name
""",
                    {"table_name": table_name, **{f"c{i}": cn for i, cn in enumerate(col_names)}},
                )
                table_rows = tx.execute_query_mappings(
                    """
SELECT
  MIN(id) AS id,
  table_name AS name,
  MAX(description) AS description
FROM workspace_table
WHERE table_name = :table_name
GROUP BY table_name
LIMIT 1
""",
                    {"table_name": table_name},
                )

            existing_map = {str(r["column_name"]): dict(r) for r in existing_columns}
            table_row = dict(table_rows[0]) if table_rows else {"id": None, "name": table_name, "description": None}
            table_state_by_name[table_name] = {
                "table_id": int(table_row.get("id") or 0),
                "table_name": str(table_row.get("name") or table_name),
                "table_description": table_row.get("description"),
                "table_columns": table_cols,
                "existing_columns": existing_map,
            }

        llm_type = type(self._llm)
        supports_table_enrichment = callable(getattr(llm_type, "generate_table_description", None))
        supports_structured_column_metadata = callable(getattr(llm_type, "generate_column_metadata", None))

        tables_total = len(table_state_by_name) if supports_table_enrichment else 0

        candidates_by_table: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for table_name, state in table_state_by_name.items():
            for col in state["table_columns"]:
                cn = str(col.get("column_name") or "").strip()
                if not cn:
                    continue
                existing_row = dict(state["existing_columns"].get(cn) or {})
                if not existing_row:
                    continue

                needs_description = overwrite or not _has_text(existing_row.get("description"))
                needs_semantic = (
                    supports_structured_column_metadata
                    and (
                        overwrite
                        or not _has_text(existing_row.get("semantic_type"))
                        or not _has_text(existing_row.get("semantic_entity"))
                        or not _has_text(existing_row.get("semantic_sub_type"))
                    )
                )
                if needs_description or needs_semantic:
                    candidates_by_table.setdefault(table_name, []).append((col, existing_row))

        columns_total = sum(len(v) for v in candidates_by_table.values())

        def _emit_progress(
            *,
            phase: str = "enrichment_columns",
            current_table: str | None = None,
            current_column: str | None = None,
        ) -> None:
            if progress_callback is None:
                return
            progress_callback(
                {
                    "phase": phase,
                    "tables_total": tables_total,
                    "tables_done": tables_done,
                    "tables_failed": tables_failed,
                    "tables_enriched": tables_enriched,
                    "columns_total": columns_total,
                    "columns_done": columns_done,
                    "columns_failed": columns_failed,
                    "columns_enriched": columns_enriched,
                    "current_table": current_table,
                    "current_column": current_column,
                }
            )

        _emit_progress(phase="enrichment_tables" if supports_table_enrichment else "enrichment_columns")

        if supports_table_enrichment:
            for table_name, state in table_state_by_name.items():
                _emit_progress(phase="enrichment_tables", current_table=table_name, current_column=None)
                try:
                    current_table_description = str(state.get("table_description") or "").strip()
                    if current_table_description and not overwrite:
                        tables_done += 1
                        _emit_progress(phase="enrichment_tables", current_table=table_name, current_column=None)
                        continue

                    context_rows: list[dict[str, Any]] = []
                    existing_map = state["existing_columns"]
                    for col in state["table_columns"]:
                        cn = str(col.get("column_name") or "").strip()
                        if not cn:
                            continue
                        existing_row = dict(existing_map.get(cn) or {})
                        context_rows.append(
                            {
                                "column_name": cn,
                                "data_type": str(col.get("data_type") or "").strip() or None,
                                "description": (
                                    str(existing_row.get("description") or "").strip()
                                    or str(col.get("comment") or "").strip()
                                    or None
                                ),
                            }
                        )

                    try:
                        generated_table_description = str(
                            self._llm.generate_table_description(
                                table_name=state["table_name"],
                                columns=context_rows,
                                workspace_id=workspace_id,
                                llm_id=llm_id,
                            )
                            or ""
                        ).strip()
                    except TypeError:
                        generated_table_description = str(
                            self._llm.generate_table_description(
                                table_name=state["table_name"],
                                columns=context_rows,
                            )
                            or ""
                        ).strip()
                    if generated_table_description:
                        with self._mysql.transaction() as tx:
                            tx.execute_write(
                                """
UPDATE workspace_table
SET description = :description, updated_at = CURRENT_TIMESTAMP
WHERE table_name = :table_name
""",
                                {
                                    "description": generated_table_description[:2000],
                                    "table_name": table_name,
                                },
                            )
                        tables_enriched += 1
                except Exception as exc:
                    logger.warning(
                        "DictionaryEnrichmentService: table LLM failed for %s: %s",
                        table_name, exc,
                    )
                    errors += 1
                    tables_failed += 1
                finally:
                    tables_done += 1
                    _emit_progress(phase="enrichment_tables", current_table=table_name, current_column=None)

        for table_name, candidates in candidates_by_table.items():
            table_description = str(table_state_by_name.get(table_name, {}).get("table_description") or "").strip() or None
            with self._mysql.transaction() as tx:
                for col, existing_row in candidates:
                    cn = str(col["column_name"])
                    _emit_progress(phase="enrichment_columns", current_table=table_name, current_column=cn)

                    try:
                        if supports_structured_column_metadata:
                            try:
                                generated = dict(
                                    self._llm.generate_column_metadata(
                                        table_name=table_name,
                                        table_description=table_description,
                                        column_name=cn,
                                        data_type=str(col.get("data_type") or "").strip() or None,
                                        source_comment=str(col.get("comment") or "").strip() or None,
                                        workspace_id=workspace_id,
                                        llm_id=llm_id,
                                    )
                                    or {}
                                )
                            except TypeError:
                                generated = dict(
                                    self._llm.generate_column_metadata(
                                        table_name=table_name,
                                        table_description=table_description,
                                        column_name=cn,
                                        data_type=str(col.get("data_type") or "").strip() or None,
                                        source_comment=str(col.get("comment") or "").strip() or None,
                                    )
                                    or {}
                                )
                        else:
                            prompt = (
                                f"Write a concise one-sentence data dictionary description for a column "
                                f"named '{cn}' of type '{col.get('data_type', 'unknown')}' "
                                f"in table '{table_name}'. "
                                f"Source comment: {col.get('comment') or 'none'}."
                            )
                            try:
                                generated = {
                                    "description": str(
                                        self._llm.generate(prompt, workspace_id=workspace_id, llm_id=llm_id) or ""
                                    ).strip() or None
                                }
                            except TypeError:
                                generated = {"description": str(self._llm.generate(prompt) or "").strip() or None}

                        sets: list[str] = []
                        params: dict[str, Any] = {}

                        current_desc = str(existing_row.get("description") or "").strip()
                        description = str(generated.get("description") or "").strip()
                        if description and (overwrite or not current_desc):
                            sets.append("description = :description")
                            params["description"] = description[:1000]

                        current_semantic_type = str(existing_row.get("semantic_type") or "").strip()
                        current_semantic_entity = str(existing_row.get("semantic_entity") or "").strip()
                        current_semantic_sub_type = str(existing_row.get("semantic_sub_type") or "").strip()
                        should_update_semantic = (
                            overwrite
                            or not current_semantic_type
                            or not current_semantic_entity
                            or not current_semantic_sub_type
                        )
                        if should_update_semantic:
                            semantic_type = str(generated.get("semantic_type") or "").strip().lower()
                            semantic_entity = str(generated.get("semantic_entity") or "").strip().lower()
                            semantic_sub_type = str(generated.get("semantic_sub_type") or "").strip().lower()
                            semantic_confidence = _coerce_confidence(generated.get("semantic_confidence"))
                            semantic_reasons = _ensure_str_list(generated.get("semantic_reasons"))

                            if semantic_type:
                                sets.append("semantic_type = :semantic_type")
                                params["semantic_type"] = semantic_type[:100]
                            if semantic_entity:
                                sets.append("semantic_entity = :semantic_entity")
                                params["semantic_entity"] = semantic_entity[:100]
                            if semantic_sub_type:
                                sets.append("semantic_sub_type = :semantic_sub_type")
                                params["semantic_sub_type"] = semantic_sub_type[:200]
                            if semantic_confidence is not None:
                                sets.append("semantic_confidence = :semantic_confidence")
                                params["semantic_confidence"] = semantic_confidence
                            if semantic_reasons:
                                sets.append("semantic_reasons_json = :semantic_reasons_json")
                                params["semantic_reasons_json"] = json.dumps(semantic_reasons, ensure_ascii=False)

                            if semantic_type or semantic_entity or semantic_sub_type:
                                sets.append("semantic_source = :semantic_source")
                                sets.append("semantic_updated_at = CURRENT_TIMESTAMP")
                                params["semantic_source"] = "llm_enrichment"

                        if sets:
                            sets.append("updated_at = CURRENT_TIMESTAMP")
                            tx.execute_write(
                                f"""
UPDATE workspace_column wc
JOIN workspace_table wt
  ON wt.id = wc.workspace_table_id
SET {", ".join(f"wc.{item}" for item in sets)}
WHERE wt.table_name = :table_name
  AND wc.column_name = :column_name
""",
                                {
                                    **params,
                                    "table_name": table_name,
                                    "column_name": cn,
                                },
                            )
                            columns_enriched += 1
                    except Exception as exc:
                        logger.warning(
                            "DictionaryEnrichmentService: LLM failed for %s.%s: %s",
                            table_name, cn, exc,
                        )
                        errors += 1
                        columns_failed += 1
                    finally:
                        columns_done += 1
                        _emit_progress(phase="enrichment_columns", current_table=table_name, current_column=cn)

        return {
            "enriched": columns_enriched,
            "errors": errors,
            "tables_total": tables_total,
            "tables_done": tables_done,
            "tables_failed": tables_failed,
            "tables_enriched": tables_enriched,
            "columns_total": columns_total,
            "columns_done": columns_done,
            "columns_failed": columns_failed,
            "columns_enriched": columns_enriched,
        }


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _coerce_confidence(value: Any) -> float | None:
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


def _ensure_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text[:120])
    return out[:10]

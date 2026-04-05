from __future__ import annotations

import inspect
import json
import logging
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import (
    SEMANTIC_AUTO_APPROVE_MAX_ERRORS,
    SEMANTIC_AUTO_APPROVE_THRESHOLD,
    SEMANTIC_LLM_BATCH_SIZE,
    SEMANTIC_VERTICAL_DEFAULT,
)
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.semantic_card_service import SemanticCardService
from app.services.semantic.semantic_assignment_service import SemanticAssignmentService
from app.services.semantic.semantic_concept_matcher import SemanticConceptMatcher
from app.services.semantic.semantic_llm_labeler import SemanticLLMLabeler
from app.services.semantic.semantic_postprocess import postprocess_semantic_proposal
from app.services.semantic.semantic_validation import validate_semantic_suggestion

RUN_STATUSES = {"created", "running", "completed", "failed", "applied"}
ITEM_DECISIONS = {"pending", "auto_approved", "approved", "rejected", "applied", "failed_apply"}
logger = logging.getLogger(__name__)
SEMANTIC_MATCHER_FALLBACK_ERRORS = (ForgeError, SQLAlchemyError)
SEMANTIC_APPLY_ITEM_FALLBACK_ERRORS = (ForgeError, SQLAlchemyError)
JSON_PARSE_ERRORS = (json.JSONDecodeError,)


class SemanticSuggestionService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        card_service: Optional[SemanticCardService] = None,
        labeler: Optional[SemanticLLMLabeler] = None,
        matcher: Optional[SemanticConceptMatcher] = None,
        assignment_service: Optional[SemanticAssignmentService] = None,
        batch_size: Optional[int] = None,
        auto_approve_threshold: Optional[float] = None,
        auto_approve_max_errors: Optional[int] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._cards = card_service or SemanticCardService(sql=self._sql)
        self._labeler = labeler or SemanticLLMLabeler()
        self._matcher = matcher or SemanticConceptMatcher(sql=self._sql)
        self._assignment = assignment_service or SemanticAssignmentService(sql=self._sql)
        self._batch_size = max(1, int(batch_size or SEMANTIC_LLM_BATCH_SIZE))
        self._auto_approve_threshold = float(
            SEMANTIC_AUTO_APPROVE_THRESHOLD if auto_approve_threshold is None else auto_approve_threshold
        )
        self._auto_approve_max_errors = int(
            SEMANTIC_AUTO_APPROVE_MAX_ERRORS if auto_approve_max_errors is None else auto_approve_max_errors
        )

    def _label_cards(
        self,
        *,
        cards: List[Dict[str, Any]],
        vertical: Optional[str],
        known_concepts: Optional[List[Dict[str, Any]]] = None,
        workspace_id: Optional[str] = None,
        llm_id: Optional[int] = None,
    ):
        kwargs = {
            "cards": cards,
            "vertical": vertical,
            "known_concepts": known_concepts,
            "workspace_id": workspace_id,
            "llm_id": llm_id,
        }
        try:
            signature = inspect.signature(self._labeler.label_cards)
        except (TypeError, ValueError):
            return self._labeler.label_cards(**kwargs)
        accepted = {
            name: value
            for name, value in kwargs.items()
            if name in signature.parameters
        }
        return self._labeler.label_cards(**accepted)

    def create_run(self, payload: Dict[str, Any], *, created_by: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        vertical = _normalize_optional_text(payload.get("vertical"), max_len=50) or SEMANTIC_VERTICAL_DEFAULT
        workspace_id = _normalize_optional_text(payload.get("workspace_id"), max_len=100)
        workspace_table_id = _normalize_optional_int(payload.get("workspace_table_id"), field="workspace_table_id")
        page_size = _normalize_optional_int(payload.get("page_size"), field="page_size") or 200

        params = {
            "workspace_table_id": workspace_table_id,
            "page_size": max(1, min(page_size, 1000)),
        }

        result = self._sql.execute_insert(
            """
            INSERT INTO semantic_suggestion_run (
              workspace_id,
              vertical,
              status,
              params_json,
              created_by
            ) VALUES (
              :workspace_id,
              :vertical,
              'created',
              :params_json,
              :created_by
            )
            """,
            {
                "workspace_id": workspace_id,
                "vertical": vertical,
                "params_json": json.dumps(params),
                "created_by": _normalize_optional_text(created_by, max_len=128),
            },
        )
        if not result.lastrowid:
            raise ForgeError("Failed to create suggestion run", status_code=500)
        return self.get_run(int(result.lastrowid))

    def execute_run(self, run_id: int, *, llm_id: Optional[int] = None) -> Dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] == "running":
            raise ForgeError("Run is already in progress", status_code=409)
        if run["status"] == "applied":
            raise ForgeError("Run already applied", status_code=409)

        params = _parse_json_obj(run.get("params_json")) or {}
        workspace_table_id = _normalize_optional_int(params.get("workspace_table_id"), field="workspace_table_id")
        page_size = _normalize_optional_int(params.get("page_size"), field="page_size") or 200
        page_size = max(1, min(page_size, 1000))
        processed_columns = 0
        vertical_norm = _normalize_vertical_norm(run.get("vertical"))
        workspace_id = str(run.get("workspace_id") or "").strip()

        self._set_run_status(run_id, status="running")
        try:
            try:
                known_concepts = self._matcher.load_known_concepts(vertical_norm)
                alias_rules = self._matcher.load_alias_rules(vertical_norm)
            except SEMANTIC_MATCHER_FALLBACK_ERRORS:
                logger.exception("Failed to load known concepts/aliases for vertical=%s", vertical_norm)
                known_concepts = []
                alias_rules = []
            total_columns = self._cards.count_columns(workspace_table_id=workspace_table_id)
            self._sql.execute_write(
                """
                UPDATE semantic_suggestion_run
                SET total_columns = :total_columns,
                    processed_columns = 0,
                    error_message = NULL
                WHERE id = :id
                """,
                {"id": int(run_id), "total_columns": int(total_columns)},
            )
            self._update_run_progress(
                run_id=int(run_id),
                params=params,
                processed_columns=processed_columns,
                state="running",
                current_card=None,
            )

            offset = 0
            while True:
                cards = self._cards.build_column_cards(
                    offset=offset,
                    limit=page_size,
                    workspace_table_id=workspace_table_id,
                )
                if not cards:
                    break

                for batch in _chunked(cards, self._batch_size):
                    outputs: List[Optional[Dict[str, Any]]] = [None] * len(batch)
                    errors: List[Optional[str]] = [None] * len(batch)
                    raws: List[Optional[Dict[str, Any]]] = [None] * len(batch)

                    unresolved_cards: List[Dict[str, Any]] = []
                    unresolved_indexes: List[int] = []

                    # Priority order: deterministic > alias(weighted) > llm > fallback.
                    for idx, card in enumerate(batch):
                        pre_output: Optional[Dict[str, Any]] = None
                        if hasattr(self._matcher, "resolve_pre_llm"):
                            pre_output, _pre_notes = self._matcher.resolve_pre_llm(
                                card=card,
                                vertical_norm=vertical_norm,
                                known_concepts=known_concepts,
                                alias_rules=alias_rules,
                                alias_conf_threshold=0.75,
                            )
                        if pre_output is not None:
                            outputs[idx] = pre_output
                            continue
                        unresolved_indexes.append(idx)
                        unresolved_cards.append(_to_llm_card(card))

                    if unresolved_cards:
                        llm_outputs, llm_errors = self._label_cards(
                            cards=unresolved_cards,
                            vertical=run.get("vertical"),
                            known_concepts=known_concepts,
                            workspace_id=workspace_id,
                            llm_id=llm_id,
                        )
                        llm_raw = getattr(self._labeler, "last_batch_raw", None)
                        if not isinstance(llm_raw, list) or len(llm_raw) != len(unresolved_cards):
                            llm_raw = [None] * len(unresolved_cards)
                        for out_idx, batch_idx in enumerate(unresolved_indexes):
                            outputs[batch_idx] = llm_outputs[out_idx]
                            errors[batch_idx] = llm_errors[out_idx]
                            raws[batch_idx] = llm_raw[out_idx] if isinstance(llm_raw[out_idx], dict) else None

                    for card, output, label_error, llm_raw in zip(batch, outputs, errors, raws, strict=True):
                        self._store_item(
                            run_id=int(run_id),
                            card=card,
                            output=output,
                            label_error=label_error,
                            llm_raw=llm_raw if isinstance(llm_raw, dict) else None,
                            vertical_norm=vertical_norm,
                            known_concepts=known_concepts,
                            alias_rules=alias_rules,
                        )
                        processed_columns += 1

                    self._update_run_progress(
                        run_id=int(run_id),
                        params=params,
                        processed_columns=processed_columns,
                        state="running",
                        current_card=batch[-1] if batch else None,
                    )

                offset += len(cards)

            self._recompute_run_counts(run_id)
            self._update_run_progress(
                run_id=int(run_id),
                params=params,
                processed_columns=processed_columns,
                state="completed",
                current_card=None,
            )
            self._set_run_status(run_id, status="completed")
        except Exception as exc:
            self._update_run_progress(
                run_id=int(run_id),
                params=params,
                processed_columns=processed_columns,
                state="failed",
                current_card=None,
            )
            self._set_run_status(run_id, status="failed", error_message=_format_exception_for_run(exc))
            if isinstance(exc, ForgeError):
                raise
            raise ForgeError("Suggestion run execution failed", status_code=500, details={"message": str(exc)}) from exc

        return self.get_run(run_id)

    def get_run(self, run_id: int) -> Dict[str, Any]:
        run_id = _require_positive_int(run_id, field="run_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              workspace_id,
              vertical,
              vertical_norm,
              status,
              params_json,
              total_columns,
              processed_columns,
              valid_items,
              invalid_items,
              auto_approved_items,
              approved_items,
              rejected_items,
              applied_items,
              failed_apply_items,
              error_message,
              started_at,
              completed_at,
              created_by,
              created_at,
              updated_at
            FROM semantic_suggestion_run
            WHERE id = :id
            LIMIT 1
            """,
            {"id": run_id},
        )
        if not rows:
            raise ForgeError("suggestion run not found", status_code=404)

        row = dict(rows[0])
        row["id"] = int(row["id"])
        for key in (
            "total_columns",
            "processed_columns",
            "valid_items",
            "invalid_items",
            "auto_approved_items",
            "approved_items",
            "rejected_items",
            "applied_items",
            "failed_apply_items",
        ):
            row[key] = int(row.get(key) or 0)
        row["params_json"] = _parse_json_obj(row.get("params_json"))
        return _to_jsonable(row)

    def list_items(
        self,
        *,
        run_id: Optional[int] = None,
        decision_status: Optional[str] = None,
        proposed_semantic_type: Optional[str] = None,
        is_valid: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        page_val = max(1, int(page or 1))
        size_val = min(200, max(1, int(page_size or 50)))
        offset = (page_val - 1) * size_val

        where = []
        params: Dict[str, Any] = {"limit": size_val, "offset": offset}

        if run_id is not None:
            where.append("ssi.run_id = :run_id")
            params["run_id"] = _require_positive_int(run_id, field="run_id")

        if decision_status is not None and str(decision_status).strip() != "":
            ds = str(decision_status).strip().lower()
            if ds not in ITEM_DECISIONS:
                raise ForgeError("invalid decision_status", status_code=400)
            where.append("ssi.decision_status = :decision_status")
            params["decision_status"] = ds

        if proposed_semantic_type is not None and str(proposed_semantic_type).strip() != "":
            where.append("ssi.proposed_semantic_type = :proposed_semantic_type")
            params["proposed_semantic_type"] = str(proposed_semantic_type).strip().lower()

        if is_valid is not None:
            where.append("ssi.is_valid = :is_valid")
            params["is_valid"] = 1 if bool(is_valid) else 0

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              ssi.id,
              ssi.run_id,
              ssi.workspace_column_id,
              ssi.workspace_table_id,
              ssi.table_name,
              ssi.column_name,
              ssi.data_type,
              ssi.description,
              ssi.samples_json,
              ssi.signals_json,
              ssi.proposed_concept_key,
              ssi.proposed_concept_id,
              ssi.proposed_concept_source,
              ssi.proposed_fallback_concept,
              ssi.proposed_concept_key_raw,
              ssi.proposed_semantic_type,
              ssi.proposed_sub_type,
              ssi.proposed_entity,
              ssi.proposed_granularity_rank,
              ssi.proposed_filter_allowed,
              ssi.proposed_group_by_allowed,
              ssi.proposed_aggregation_allowed,
              ssi.proposed_is_identifier,
              ssi.proposed_is_metric,
              ssi.proposed_display_priority,
              ssi.proposed_sensitive,
              ssi.confidence,
              ssi.reasons_json,
              ssi.warnings_json,
              ssi.validation_errors_json,
              ssi.is_valid,
              ssi.decision_status,
              ssi.decision_reason,
              ssi.applied_at,
              ssi.created_at,
              ssi.updated_at
            FROM semantic_suggestion_item ssi
            {where_sql}
            ORDER BY ssi.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM semantic_suggestion_item ssi
            {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0

        return {
            "rows": [self._normalize_item_row(row) for row in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def update_item(self, item_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        item_id = _require_positive_int(item_id, field="item_id")
        if not isinstance(payload, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        item = self._get_item(item_id)
        decision_status = payload.get("decision_status")
        decision_reason = _normalize_optional_text(payload.get("decision_reason"), max_len=255)

        updates: Dict[str, Any] = {}
        if decision_status is not None:
            ds = str(decision_status).strip().lower()
            if ds in {"approve", "approved"}:
                ds = "approved"
            elif ds in {"reject", "rejected"}:
                ds = "rejected"
            if ds not in {"approved", "rejected", "pending"}:
                raise ForgeError("decision_status must be approved, rejected, or pending", status_code=400)
            if ds == "approved" and not bool(item.get("is_valid")):
                raise ForgeError("Cannot approve invalid item", status_code=400)
            updates["decision_status"] = ds

        if "decision_reason" in payload:
            updates["decision_reason"] = decision_reason

        if not updates:
            return item

        set_parts = [f"{key} = :{key}" for key in updates.keys()]
        updates["id"] = item_id
        self._sql.execute_write(
            f"""
            UPDATE semantic_suggestion_item
            SET {', '.join(set_parts)}
            WHERE id = :id
            """,
            updates,
        )
        self._recompute_run_counts(int(item["run_id"]))
        return self._get_item(item_id)

    def apply_approved(self, run_id: int) -> Dict[str, Any]:
        run_id = _require_positive_int(run_id, field="run_id")
        run = self.get_run(run_id)

        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM semantic_suggestion_item
            WHERE run_id = :run_id
              AND is_valid = 1
              AND decision_status IN ('auto_approved', 'approved')
              AND applied_at IS NULL
            ORDER BY id ASC
            """,
            {"run_id": run_id},
        )

        for row in rows:
            item = self._normalize_item_row(row)
            try:
                registry_id = self._upsert_registry(run=run, item=item)
                self._upsert_mapping(run=run, item=item, semantic_registry_id=registry_id)
                self._upsert_model_column_semantics_from_item(run=run, item=item)
                self._sql.execute_write(
                    """
                    UPDATE semantic_suggestion_item
                    SET decision_status = 'applied',
                        decision_reason = NULL,
                        applied_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """,
                    {"id": int(item["id"])},
                )
            except SEMANTIC_APPLY_ITEM_FALLBACK_ERRORS as exc:
                self._sql.execute_write(
                    """
                    UPDATE semantic_suggestion_item
                    SET decision_status = 'failed_apply',
                        decision_reason = :reason
                    WHERE id = :id
                    """,
                    {"id": int(item["id"]), "reason": str(exc)[:255]},
                )

        self._recompute_run_counts(run_id)
        refreshed = self.get_run(run_id)
        status = "applied" if refreshed["failed_apply_items"] == 0 else "completed"
        self._set_run_status(run_id, status=status)
        return self.get_run(run_id)

    def _store_item(
        self,
        *,
        run_id: int,
        card: Dict[str, Any],
        output: Optional[Dict[str, Any]],
        label_error: Optional[str],
        llm_raw: Optional[Dict[str, Any]],
        vertical_norm: str,
        known_concepts: List[Dict[str, Any]],
        alias_rules: List[Dict[str, Any]],
    ) -> None:
        if output is None:
            validated = {
                "concept_key": None,
                "concept_key_raw": None,
                "concept_id": None,
                "concept_source": "fallback",
                "fallback_concept": True,
                "semantic_type": None,
                "sub_type": None,
                "entity": None,
                "granularity_rank": 0,
                "filter_allowed": True,
                "group_by_allowed": True,
                "aggregation_allowed": True,
                "is_identifier": False,
                "is_metric": False,
                "display_priority": 0,
                "sensitive": False,
                "confidence": 0.0,
                "reasons": [],
                "warnings": [],
                "validation_errors": [label_error or "llm_invalid_output"],
                "is_valid": False,
                "decision_status": "pending",
            }
            llm_raw_json = llm_raw
        else:
            raw_concept_key = output.get("concept_key")
            processed_output, postprocess_notes = postprocess_semantic_proposal(card=card, proposal=output)
            matched_output, matcher_notes = self._matcher.enforce_canonical_if_strong(
                card=card,
                proposal=processed_output,
                vertical_norm=vertical_norm,
                known_concepts=known_concepts,
                alias_rules=alias_rules,
            )
            validated = validate_semantic_suggestion(
                output=matched_output,
                card=card,
                auto_approve_threshold=self._auto_approve_threshold,
                auto_approve_max_errors=self._auto_approve_max_errors,
            )
            concept_source = str(matched_output.get("concept_source") or "fallback").strip().lower()
            if concept_source not in {"llm", "alias", "deterministic", "fallback"}:
                concept_source = "fallback"
            concept_key = str(validated.get("concept_key") or "").strip()
            concept_id = self._resolve_concept_id(
                concept_key=concept_key,
                vertical_norm=vertical_norm,
                concept_source=concept_source,
            )
            validated["concept_key_raw"] = str(raw_concept_key) if raw_concept_key is not None else None
            validated["concept_source"] = concept_source
            validated["fallback_concept"] = concept_source == "fallback"
            validated["concept_id"] = concept_id
            merged_warnings = list(validated.get("warnings") or [])
            merged_warnings.extend(postprocess_notes)
            merged_warnings.extend(matcher_notes)
            validated["warnings"] = _unique_strs(merged_warnings)
            llm_raw_json = llm_raw or output

        self._sql.execute_write(
            """
            INSERT INTO semantic_suggestion_item (
              run_id,
              workspace_column_id,
              workspace_table_id,
              table_name,
              column_name,
              data_type,
              description,
              samples_json,
              signals_json,
              llm_raw_json,
              proposed_concept_key,
              proposed_concept_id,
              proposed_concept_source,
              proposed_fallback_concept,
              proposed_concept_key_raw,
              proposed_semantic_type,
              proposed_sub_type,
              proposed_entity,
              proposed_granularity_rank,
              proposed_filter_allowed,
              proposed_group_by_allowed,
              proposed_aggregation_allowed,
              proposed_is_identifier,
              proposed_is_metric,
              proposed_display_priority,
              proposed_sensitive,
              confidence,
              reasons_json,
              warnings_json,
              validation_errors_json,
              is_valid,
              decision_status
            ) VALUES (
              :run_id,
              :workspace_column_id,
              :workspace_table_id,
              :table_name,
              :column_name,
              :data_type,
              :description,
              :samples_json,
              :signals_json,
              :llm_raw_json,
              :proposed_concept_key,
              :proposed_concept_id,
              :proposed_concept_source,
              :proposed_fallback_concept,
              :proposed_concept_key_raw,
              :proposed_semantic_type,
              :proposed_sub_type,
              :proposed_entity,
              :proposed_granularity_rank,
              :proposed_filter_allowed,
              :proposed_group_by_allowed,
              :proposed_aggregation_allowed,
              :proposed_is_identifier,
              :proposed_is_metric,
              :proposed_display_priority,
              :proposed_sensitive,
              :confidence,
              :reasons_json,
              :warnings_json,
              :validation_errors_json,
              :is_valid,
              :decision_status
            )
            ON DUPLICATE KEY UPDATE
              workspace_table_id = VALUES(workspace_table_id),
              table_name = VALUES(table_name),
              column_name = VALUES(column_name),
              data_type = VALUES(data_type),
              description = VALUES(description),
              samples_json = VALUES(samples_json),
              signals_json = VALUES(signals_json),
              llm_raw_json = VALUES(llm_raw_json),
              proposed_concept_key = VALUES(proposed_concept_key),
              proposed_concept_id = VALUES(proposed_concept_id),
              proposed_concept_source = VALUES(proposed_concept_source),
              proposed_fallback_concept = VALUES(proposed_fallback_concept),
              proposed_concept_key_raw = VALUES(proposed_concept_key_raw),
              proposed_semantic_type = VALUES(proposed_semantic_type),
              proposed_sub_type = VALUES(proposed_sub_type),
              proposed_entity = VALUES(proposed_entity),
              proposed_granularity_rank = VALUES(proposed_granularity_rank),
              proposed_filter_allowed = VALUES(proposed_filter_allowed),
              proposed_group_by_allowed = VALUES(proposed_group_by_allowed),
              proposed_aggregation_allowed = VALUES(proposed_aggregation_allowed),
              proposed_is_identifier = VALUES(proposed_is_identifier),
              proposed_is_metric = VALUES(proposed_is_metric),
              proposed_display_priority = VALUES(proposed_display_priority),
              proposed_sensitive = VALUES(proposed_sensitive),
              confidence = VALUES(confidence),
              reasons_json = VALUES(reasons_json),
              warnings_json = VALUES(warnings_json),
              validation_errors_json = VALUES(validation_errors_json),
              is_valid = VALUES(is_valid),
              decision_status = VALUES(decision_status)
            """,
            {
                "run_id": run_id,
                "workspace_column_id": int(card["workspaceColumnId"]),
                "workspace_table_id": card.get("workspaceTableId"),
                "table_name": card.get("tableName"),
                "column_name": card.get("columnName"),
                "data_type": card.get("dataType"),
                "description": card.get("description"),
                "samples_json": json.dumps(card.get("samples") or []),
                "signals_json": json.dumps(card.get("signals") or {}),
                "llm_raw_json": json.dumps(llm_raw_json) if llm_raw_json is not None else None,
                "proposed_concept_key": validated.get("concept_key"),
                "proposed_concept_id": validated.get("concept_id"),
                "proposed_concept_source": validated.get("concept_source") or "fallback",
                "proposed_fallback_concept": 1 if bool(validated.get("fallback_concept")) else 0,
                "proposed_concept_key_raw": validated.get("concept_key_raw"),
                "proposed_semantic_type": validated.get("semantic_type"),
                "proposed_sub_type": validated.get("sub_type"),
                "proposed_entity": validated.get("entity"),
                "proposed_granularity_rank": int(validated.get("granularity_rank") or 0),
                "proposed_filter_allowed": 1 if bool(validated.get("filter_allowed", True)) else 0,
                "proposed_group_by_allowed": 1 if bool(validated.get("group_by_allowed", True)) else 0,
                "proposed_aggregation_allowed": 1 if bool(validated.get("aggregation_allowed", True)) else 0,
                "proposed_is_identifier": 1 if bool(validated.get("is_identifier", False)) else 0,
                "proposed_is_metric": 1 if bool(validated.get("is_metric", False)) else 0,
                "proposed_display_priority": int(validated.get("display_priority") or 0),
                "proposed_sensitive": 1 if bool(validated.get("sensitive", False)) else 0,
                "confidence": round(float(validated.get("confidence") or 0.0), 4),
                "reasons_json": json.dumps(validated.get("reasons") or []),
                "warnings_json": json.dumps(validated.get("warnings") or []),
                "validation_errors_json": json.dumps(validated.get("validation_errors") or []),
                "is_valid": 1 if bool(validated.get("is_valid")) else 0,
                "decision_status": validated.get("decision_status") or "pending",
            },
        )

    def _resolve_concept_id(self, *, concept_key: str, vertical_norm: str, concept_source: str) -> Optional[int]:
        key = str(concept_key or "").strip()
        if not key or concept_source == "fallback":
            return None
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM semantic_concept
            WHERE concept_key = :concept_key
              AND vertical_norm IN (:vertical_norm, 'generic')
            ORDER BY CASE WHEN vertical_norm = :vertical_norm THEN 0 ELSE 1 END
            LIMIT 1
            """,
            {"concept_key": key, "vertical_norm": _normalize_vertical_norm(vertical_norm)},
        )
        if not rows:
            return None
        row_id = rows[0].get("id")
        if row_id is None:
            return None
        try:
            return int(row_id)
        except (TypeError, ValueError):
            return None

    def _upsert_registry(self, *, run: Dict[str, Any], item: Dict[str, Any]) -> int:
        concept_key = str(item.get("proposed_concept_key") or "").strip()
        if not concept_key:
            raise ForgeError("Missing proposed_concept_key", status_code=400)

        vertical_norm = _normalize_vertical_norm(run.get("vertical"))
        registry_source = self._resolve_registry_source(item=item, vertical_norm=vertical_norm)

        self._sql.execute_write(
            """
            INSERT INTO semantic_registry (
              vertical,
              concept_key,
              semantic_type,
              sub_type,
              entity,
              description,
              granularity_rank,
              filter_allowed,
              group_by_allowed,
              aggregation_allowed,
              is_identifier,
              is_metric,
              display_priority,
              `sensitive`
            ) VALUES (
              :vertical,
              :concept_key,
              :semantic_type,
              :sub_type,
              :entity,
              :description,
              :granularity_rank,
              :filter_allowed,
              :group_by_allowed,
              :aggregation_allowed,
              :is_identifier,
              :is_metric,
              :display_priority,
              :sensitive
            )
            ON DUPLICATE KEY UPDATE
              semantic_type = VALUES(semantic_type),
              sub_type = VALUES(sub_type),
              entity = VALUES(entity),
              description = VALUES(description),
              granularity_rank = VALUES(granularity_rank),
              filter_allowed = VALUES(filter_allowed),
              group_by_allowed = VALUES(group_by_allowed),
              aggregation_allowed = VALUES(aggregation_allowed),
              is_identifier = VALUES(is_identifier),
              is_metric = VALUES(is_metric),
              display_priority = VALUES(display_priority),
              `sensitive` = VALUES(`sensitive`)
            """,
            {
                "vertical": (
                    None
                    if _normalize_vertical_norm(registry_source["vertical"]) == "__global__"
                    else _normalize_vertical_norm(registry_source["vertical"])
                ),
                "concept_key": concept_key,
                "semantic_type": registry_source["semantic_type"],
                "sub_type": registry_source["sub_type"],
                "entity": registry_source["entity"],
                "description": registry_source["description"],
                "granularity_rank": int(registry_source["granularity_rank"]),
                "filter_allowed": 1 if bool(registry_source["filter_allowed"]) else 0,
                "group_by_allowed": 1 if bool(registry_source["group_by_allowed"]) else 0,
                "aggregation_allowed": 1 if bool(registry_source["aggregation_allowed"]) else 0,
                "is_identifier": 1 if bool(registry_source["is_identifier"]) else 0,
                "is_metric": 1 if bool(registry_source["is_metric"]) else 0,
                "display_priority": int(registry_source["display_priority"]),
                "sensitive": 1 if bool(registry_source["sensitive"]) else 0,
            },
        )

        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM semantic_registry
            WHERE vertical_norm = :vertical_norm
              AND concept_key = :concept_key
            LIMIT 1
            """,
            {
                "vertical_norm": _normalize_vertical_norm(registry_source["vertical"]),
                "concept_key": concept_key,
            },
        )
        if not rows:
            raise ForgeError("Failed to resolve semantic_registry id", status_code=500)
        return int(rows[0]["id"])

    def _upsert_mapping(self, *, run: Dict[str, Any], item: Dict[str, Any], semantic_registry_id: int) -> None:
        self._sql.execute_write(
            """
            INSERT INTO semantic_column_map (
              semantic_registry_id,
              workspace_id,
              workspace_column_id,
              table_name,
              column_name,
              priority_rank,
              confidence_score
            ) VALUES (
              :semantic_registry_id,
              :workspace_id,
              :workspace_column_id,
              :table_name,
              :column_name,
              :priority_rank,
              :confidence_score
            )
            ON DUPLICATE KEY UPDATE
              priority_rank = VALUES(priority_rank),
              confidence_score = VALUES(confidence_score)
            """,
            {
                "semantic_registry_id": int(semantic_registry_id),
                "workspace_id": run.get("workspace_id"),
                "workspace_column_id": int(item["workspace_column_id"]),
                "table_name": None,
                "column_name": None,
                "priority_rank": int(item.get("proposed_display_priority") or 0),
                "confidence_score": round(float(item.get("confidence") or 0.0), 3),
            },
        )

    def _upsert_model_column_semantics_from_item(self, *, run: Dict[str, Any], item: Dict[str, Any]) -> None:
        concept_id_val = item.get("proposed_concept_id")
        concept_id = int(concept_id_val) if concept_id_val is not None else None
        concept_key = str(item.get("proposed_concept_key") or "").strip() or None
        source = str(item.get("proposed_concept_source") or "").strip().lower() or None
        confidence_val = item.get("confidence")
        confidence = float(confidence_val) if confidence_val is not None else None

        reasons = item.get("reasons_json")
        if not isinstance(reasons, list):
            reasons = []
        warnings = item.get("warnings_json")
        if not isinstance(warnings, list):
            warnings = []

        self._assignment.upsert_primary_semantics(
            workspace_column_id=int(item["workspace_column_id"]),
            semantic_concept_id=concept_id,
            key=concept_key,
            source=source,
            confidence=confidence,
            reasons=[str(v) for v in reasons],
            warnings=[str(v) for v in warnings],
            entity=item.get("proposed_entity"),
            sub_type=item.get("proposed_sub_type"),
            granularity_rank=int(item.get("proposed_granularity_rank") or 0),
        )

        if concept_id is not None:
            vertical_norm = _normalize_vertical_norm(run.get("vertical"))
            if vertical_norm == "__global__":
                vertical_norm = "generic"
            self._assignment.ensure_mapping(
                workspace_column_id=int(item["workspace_column_id"]),
                semantic_concept_id=concept_id,
                relationship_kind="primary",
                weight=max(0.0, float(confidence or 0.0)),
                vertical_norm=vertical_norm,
            )

    def _resolve_registry_source(self, *, item: Dict[str, Any], vertical_norm: str) -> Dict[str, Any]:
        concept_id = item.get("proposed_concept_id")
        if concept_id is not None:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  vertical_norm,
                  semantic_type,
                  sub_type,
                  entity,
                  description,
                  granularity_rank,
                  filter_allowed,
                  group_by_allowed,
                  aggregation_allowed,
                  is_identifier,
                  is_metric,
                  display_priority,
                  `sensitive` AS `sensitive`
                FROM semantic_concept
                WHERE id = :id
                LIMIT 1
                """,
                {"id": int(concept_id)},
            )
            if rows:
                concept = rows[0]
                return {
                    "vertical": concept.get("vertical_norm") or vertical_norm,
                    "semantic_type": concept.get("semantic_type") or item.get("proposed_semantic_type") or "attribute",
                    "sub_type": concept.get("sub_type"),
                    "entity": concept.get("entity"),
                    "description": concept.get("description") or item.get("description"),
                    "granularity_rank": int(concept.get("granularity_rank") or 0),
                    "filter_allowed": bool(concept.get("filter_allowed")),
                    "group_by_allowed": bool(concept.get("group_by_allowed")),
                    "aggregation_allowed": bool(concept.get("aggregation_allowed")),
                    "is_identifier": bool(concept.get("is_identifier")),
                    "is_metric": bool(concept.get("is_metric")),
                    "display_priority": int(concept.get("display_priority") or 0),
                    "sensitive": bool(concept.get("sensitive")),
                }

        fallback_type = item.get("proposed_semantic_type") or "attribute"
        return {
            "vertical": vertical_norm,
            "semantic_type": fallback_type,
            "sub_type": item.get("proposed_sub_type"),
            "entity": item.get("proposed_entity"),
            "description": item.get("description"),
            "granularity_rank": int(item.get("proposed_granularity_rank") or 0),
            "filter_allowed": bool(item.get("proposed_filter_allowed")),
            "group_by_allowed": bool(item.get("proposed_group_by_allowed")),
            "aggregation_allowed": bool(item.get("proposed_aggregation_allowed")),
            "is_identifier": bool(item.get("proposed_is_identifier")),
            "is_metric": bool(item.get("proposed_is_metric")),
            "display_priority": int(item.get("proposed_display_priority") or 0),
            "sensitive": bool(item.get("proposed_sensitive")),
        }

    def _recompute_run_counts(self, run_id: int) -> None:
        counts = self._sql.execute_query_mappings(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN is_valid = 1 THEN 1 ELSE 0 END) AS valid_items,
              SUM(CASE WHEN is_valid = 0 THEN 1 ELSE 0 END) AS invalid_items,
              SUM(CASE WHEN decision_status = 'auto_approved' THEN 1 ELSE 0 END) AS auto_approved_items,
              SUM(CASE WHEN decision_status = 'approved' THEN 1 ELSE 0 END) AS approved_items,
              SUM(CASE WHEN decision_status = 'rejected' THEN 1 ELSE 0 END) AS rejected_items,
              SUM(CASE WHEN decision_status = 'applied' THEN 1 ELSE 0 END) AS applied_items,
              SUM(CASE WHEN decision_status = 'failed_apply' THEN 1 ELSE 0 END) AS failed_apply_items
            FROM semantic_suggestion_item
            WHERE run_id = :run_id
            """,
            {"run_id": int(run_id)},
        )
        row = counts[0] if counts else {}

        self._sql.execute_write(
            """
            UPDATE semantic_suggestion_run
            SET processed_columns = :processed_columns,
                valid_items = :valid_items,
                invalid_items = :invalid_items,
                auto_approved_items = :auto_approved_items,
                approved_items = :approved_items,
                rejected_items = :rejected_items,
                applied_items = :applied_items,
                failed_apply_items = :failed_apply_items
            WHERE id = :id
            """,
            {
                "id": int(run_id),
                "processed_columns": int(row.get("total") or 0),
                "valid_items": int(row.get("valid_items") or 0),
                "invalid_items": int(row.get("invalid_items") or 0),
                "auto_approved_items": int(row.get("auto_approved_items") or 0),
                "approved_items": int(row.get("approved_items") or 0),
                "rejected_items": int(row.get("rejected_items") or 0),
                "applied_items": int(row.get("applied_items") or 0),
                "failed_apply_items": int(row.get("failed_apply_items") or 0),
            },
        )

    def _set_run_status(self, run_id: int, *, status: str, error_message: Optional[str] = None) -> None:
        if status not in RUN_STATUSES:
            raise ForgeError("invalid run status", status_code=400)

        set_parts = ["status = :status"]
        params: Dict[str, Any] = {"id": int(run_id), "status": status}

        if status == "running":
            set_parts.append("started_at = CURRENT_TIMESTAMP")
            set_parts.append("completed_at = NULL")
        if status in {"completed", "failed", "applied"}:
            set_parts.append("completed_at = CURRENT_TIMESTAMP")
        if error_message is not None:
            set_parts.append("error_message = :error_message")
            params["error_message"] = error_message

        self._sql.execute_write(
            f"""
            UPDATE semantic_suggestion_run
            SET {', '.join(set_parts)}
            WHERE id = :id
            """,
            params,
        )

    def _update_run_progress(
        self,
        *,
        run_id: int,
        params: Dict[str, Any],
        processed_columns: int,
        state: str,
        current_card: Optional[Dict[str, Any]],
    ) -> None:
        params_copy = dict(params)
        progress: Dict[str, Any] = {
            "state": state,
            "processed_columns": int(processed_columns),
        }
        if current_card:
            progress["last_workspace_column_id"] = current_card.get("workspaceColumnId")
            progress["last_workspace_table_id"] = current_card.get("workspaceTableId")
            progress["last_table_name"] = current_card.get("tableName")
            progress["last_column_name"] = current_card.get("columnName")
        params_copy["progress"] = progress
        self._sql.execute_write(
            """
            UPDATE semantic_suggestion_run
            SET processed_columns = :processed_columns,
                params_json = :params_json
            WHERE id = :id
            """,
            {
                "id": int(run_id),
                "processed_columns": int(processed_columns),
                "params_json": json.dumps(params_copy),
            },
        )

    def _get_item(self, item_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM semantic_suggestion_item
            WHERE id = :id
            LIMIT 1
            """,
            {"id": int(item_id)},
        )
        if not rows:
            raise ForgeError("suggestion item not found", status_code=404)
        return self._normalize_item_row(rows[0])

    @staticmethod
    def _normalize_item_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        if out.get("workspace_column_id") is None and out.get("model_column_id") is not None:
            out["workspace_column_id"] = out.get("model_column_id")
        if out.get("workspace_table_id") is None and out.get("model_table_id") is not None:
            out["workspace_table_id"] = out.get("model_table_id")
        int_fields = {
            "id",
            "run_id",
            "workspace_column_id",
            "workspace_table_id",
            "proposed_concept_id",
            "proposed_granularity_rank",
            "proposed_display_priority",
        }
        bool_fields = {
            "proposed_fallback_concept",
            "proposed_filter_allowed",
            "proposed_group_by_allowed",
            "proposed_aggregation_allowed",
            "proposed_is_identifier",
            "proposed_is_metric",
            "proposed_sensitive",
            "is_valid",
        }

        for key in int_fields:
            if out.get(key) is not None:
                out[key] = int(out[key])
        if out.get("workspace_column_id") is not None:
            out["model_column_id"] = int(out["workspace_column_id"])
        if out.get("workspace_table_id") is not None:
            out["model_table_id"] = int(out["workspace_table_id"])
        for key in bool_fields:
            if key in out:
                out[key] = bool(out[key])
        if out.get("confidence") is not None:
            out["confidence"] = float(out["confidence"])

        for json_key in ("samples_json", "signals_json", "llm_raw_json", "reasons_json", "warnings_json", "validation_errors_json"):
            out[json_key] = _parse_json_any(out.get(json_key))

        return _to_jsonable(out)


def _chunked(items: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _normalize_optional_text(value: Any, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if len(text) > max_len:
        raise ForgeError(f"value exceeds {max_len} characters", status_code=400)
    return text


def _normalize_vertical_norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"", "global", "__global__", "null", "none"}:
        return "__global__"
    return text


def _normalize_optional_int(value: Any, *, field: str) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ForgeError(f"{field} must be an integer", status_code=400) from exc


def _require_positive_int(value: Any, *, field: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ForgeError(f"{field} must be a positive integer", status_code=400) from exc
    if out <= 0:
        raise ForgeError(f"{field} must be a positive integer", status_code=400)
    return out


def _parse_json_obj(value: Any) -> Optional[Dict[str, Any]]:
    parsed = _parse_json_any(value)
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_json_any(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return json.loads(text)
        except JSON_PARSE_ERRORS:
            return None
    return value


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _to_llm_card(card: Dict[str, Any]) -> Dict[str, Any]:
    description = card.get("description")
    return {
        "tableName": card.get("tableName"),
        "columnName": card.get("columnName"),
        "dataType": card.get("dataType"),
        "description": (str(description)[:240] if description is not None else None),
    }


def _format_exception_for_run(exc: Exception) -> str:
    if isinstance(exc, ForgeError):
        message = str(exc.message or "ForgeError")
        details = exc.details or {}
        if details:
            try:
                details_text = json.dumps(_to_jsonable(details), ensure_ascii=True)
            except (TypeError, ValueError):
                details_text = str(details)
            return f"{message} | details={details_text}"[:8000]
        return message[:8000]
    return str(exc)[:8000]


def _unique_strs(values: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out

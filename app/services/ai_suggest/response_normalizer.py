# app/services/ai_suggest/response_normalizer.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from app.services.ai_suggest.utils import (
    ALLOWED_EDIT_OPS,
    LEGACY_FILTER_OPERATOR_MAP,
    _sanitize_col,
)

logger = logging.getLogger(__name__)


class ResponseNormalizer:
    """Normalizes raw model JSON payload into a validated edit list."""

    def normalize(self, payload: Any) -> Tuple[Any, Dict[str, int]]:
        meta = {"rewritten_ops": 0, "dropped_edits": 0}
        if not isinstance(payload, dict):
            return payload, meta

        payload.setdefault("edits", [])
        payload.setdefault("explanation", "")
        payload.setdefault("confidence", 0.5)

        explanation = payload.get("explanation")
        if not isinstance(explanation, str):
            payload["explanation"] = str(explanation)

        confidence_raw = payload.get("confidence", 0.5)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.5
        payload["confidence"] = max(0.0, min(1.0, confidence))

        edits = payload.get("edits")
        if not isinstance(edits, list):
            return payload, meta

        normalized_edits: List[Dict[str, Any]] = []
        for edit in edits:
            if not isinstance(edit, dict):
                meta["dropped_edits"] += 1
                continue

            if "op" not in edit and "operation" in edit:
                edit["op"] = edit.pop("operation")
                meta["rewritten_ops"] += 1
            elif "op" not in edit and "action" in edit:
                edit["op"] = edit.pop("action")
                meta["rewritten_ops"] += 1

            op = edit.get("op")
            if op not in ALLOWED_EDIT_OPS:
                meta["dropped_edits"] += 1
                continue

            drop_edit = self._normalize_edit_column_shape(edit)
            if drop_edit:
                meta["dropped_edits"] += 1
                continue
            if op == "addFilter":
                raw_operator = edit.get("operator")
                if isinstance(raw_operator, str) and raw_operator in LEGACY_FILTER_OPERATOR_MAP:
                    edit["operator"] = LEGACY_FILTER_OPERATOR_MAP[raw_operator]
            elif op == "addSort":
                if "dir" not in edit and "direction" in edit:
                    edit["dir"] = edit.pop("direction")
                raw_dir = edit.get("dir")
                if isinstance(raw_dir, str):
                    dir_lc = raw_dir.lower()
                    if dir_lc == "descending":
                        dir_lc = "desc"
                    elif dir_lc == "ascending":
                        dir_lc = "asc"
                    edit["dir"] = dir_lc

            normalized_edits.append(edit)

        payload["edits"] = normalized_edits

        if meta["rewritten_ops"] or meta["dropped_edits"]:
            logger.info(
                "AI suggest normalization rewrote_ops=%s dropped_edits=%s",
                meta["rewritten_ops"],
                meta["dropped_edits"],
            )
        return payload, meta

    def _normalize_edit_column_shape(self, edit: Dict[str, Any]) -> bool:
        if "col" in edit:
            if isinstance(edit["col"], dict):
                edit["col"] = _sanitize_col(edit["col"])
                if "columnName" not in edit["col"]:
                    return True
                self._ensure_sql_column_key_defaults(edit["col"])
            return False

        alias_value = None
        for alias in ("columnKey", "field", "column"):
            if alias in edit:
                alias_value = edit.pop(alias)
                break

        if isinstance(alias_value, dict):
            edit["col"] = _sanitize_col(alias_value)
            if "columnName" not in edit["col"]:
                return True
            self._ensure_sql_column_key_defaults(edit["col"])
            return False
        if isinstance(alias_value, str) and alias_value.strip():
            edit["col"] = self._sql_column_key_from_legacy_string(alias_value)
            return False
        if alias_value is not None:
            edit["col"] = alias_value
            return False
        return False

    def _sql_column_key_from_legacy_string(self, value: str) -> Dict[str, Any]:
        text = value.strip()
        column_name = text.split(".")[-1] if "." in text else text
        return {
            "modelColumnId": None,
            "columnName": column_name,
            "workspaceTableId": None,
            "exprId": None,
            "alias": None,
        }

    def _ensure_sql_column_key_defaults(self, key: Dict[str, Any]) -> None:
        key.setdefault("modelColumnId", None)
        key.setdefault("workspaceTableId", None)
        key.setdefault("exprId", None)
        key.setdefault("alias", None)

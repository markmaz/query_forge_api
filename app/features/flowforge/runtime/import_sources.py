from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError


@dataclass(frozen=True)
class ImportSourceReadResult:
    rows: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    source_ref: dict[str, Any]
    byte_count: int
    checksum: str


class LocalFileTestImportAdapter:
    def read(
        self,
        *,
        source: dict[str, Any],
        config: dict[str, Any],
    ) -> ImportSourceReadResult:
        if str(source.get("source_type") or "").strip() != "local_file_test":
            raise FlowForgeNodeExecutionError(
                "Only local_file_test import sources are executable in this phase."
            )
        if str(source.get("mode") or "test").strip() != "test":
            raise FlowForgeNodeExecutionError(
                "local_file_test imports require a test-mode source."
            )
        path = self._resolve_path(source=source, config=config)
        if not path.exists() or not path.is_file():
            raise FlowForgeNodeExecutionError(f"Import source file '{path}' was not found.")
        raw = path.read_bytes()
        rows = self._parse_rows(path=path, raw=raw)
        return ImportSourceReadResult(
            rows=rows,
            columns=self._columns(rows),
            source_ref={
                "source_type": "local_file_test",
                "source_key": source.get("source_key"),
                "path": str(path),
                "filename": path.name,
            },
            byte_count=len(raw),
            checksum="sha256:" + hashlib.sha256(raw).hexdigest(),
        )

    def _resolve_path(self, *, source: dict[str, Any], config: dict[str, Any]) -> Path:
        source_config = source.get("config_json") or source.get("config") or {}
        if not isinstance(source_config, dict):
            source_config = {}
        base_dir_value = str(source_config.get("base_dir") or "").strip()
        if not base_dir_value:
            raise FlowForgeNodeExecutionError("local_file_test import source requires config.base_dir.")
        base_dir = Path(base_dir_value).expanduser()
        filename = str(config.get("filename") or source_config.get("filename") or "").strip()
        if not filename:
            raise FlowForgeNodeExecutionError("import requires filename for local_file_test sources.")
        candidate = (base_dir / filename).resolve()
        resolved_base = base_dir.resolve()
        if resolved_base not in candidate.parents and candidate != resolved_base:
            raise FlowForgeNodeExecutionError("Import filename must stay within the configured source base_dir.")
        return candidate

    def _parse_rows(self, *, path: Path, raw: bytes) -> list[dict[str, Any]]:
        text = raw.decode("utf-8-sig")
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return [dict(row) for row in csv.DictReader(text.splitlines())]
        if suffix == ".json":
            parsed = json.loads(text)
            records = parsed.get("records") if isinstance(parsed, dict) else parsed
            if not isinstance(records, list):
                raise FlowForgeNodeExecutionError("JSON import files must contain an array or a records array.")
            return [row for row in records if isinstance(row, dict)]
        raise FlowForgeNodeExecutionError("local_file_test imports support CSV and JSON files only.")

    def _columns(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        return [{"key": key, "label": key.replace("_", " ").title()} for key in keys]

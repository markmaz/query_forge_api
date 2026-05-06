from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError


@dataclass(frozen=True)
class ExportWriteResult:
    destination_ref: dict[str, Any]
    row_count: int
    byte_count: int
    checksum: str
    format: str


class LocalFileTestExportAdapter:
    def write(
        self,
        *,
        rows: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        destination: dict[str, Any],
        config: dict[str, Any],
        run_id: int,
        node_id: str,
    ) -> ExportWriteResult:
        export_format = str(config.get("format") or "csv").strip().lower()
        if export_format != "csv":
            raise FlowForgeNodeExecutionError(
                "local_file_test exports currently support csv only."
            )
        base_dir = self._base_dir(destination)
        base_dir.mkdir(parents=True, exist_ok=True)
        output_path = base_dir / self._filename(
            config=config, run_id=run_id, node_id=node_id
        )
        fieldnames = self._fieldnames(columns=columns, rows=rows)
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        payload = output_path.read_bytes()
        return ExportWriteResult(
            destination_ref={
                "destination_key": destination.get("destination_key"),
                "destination_type": destination.get("destination_type"),
                "path": str(output_path),
            },
            row_count=len(rows),
            byte_count=len(payload),
            checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            format=export_format,
        )

    def _base_dir(self, destination: dict[str, Any]) -> Path:
        config = destination.get("config_json") or destination.get("config") or {}
        base_dir = (
            str(config.get("base_dir") or "/tmp/queryforge-flowforge-exports").strip()
            if isinstance(config, dict)
            else ""
        )
        if not base_dir:
            raise FlowForgeNodeExecutionError(
                "local_file_test destination requires base_dir."
            )
        return Path(base_dir).expanduser().resolve()

    def _filename(self, *, config: dict[str, Any], run_id: int, node_id: str) -> str:
        raw = str(
            config.get("filename") or f"flowforge-run-{int(run_id)}-{node_id}.csv"
        ).strip()
        safe = "".join(
            ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in raw
        )
        if not safe.endswith(".csv"):
            safe = f"{safe}.csv"
        return safe

    def _fieldnames(
        self, *, columns: list[dict[str, Any]], rows: list[dict[str, Any]]
    ) -> list[str]:
        fieldnames = [
            str(column.get("key") or column.get("name") or "").strip()
            for column in columns
            if str(column.get("key") or column.get("name") or "").strip()
        ]
        if fieldnames:
            return fieldnames
        seen: set[str] = set()
        for row in rows:
            for key in row:
                seen.add(key)
        return sorted(seen)

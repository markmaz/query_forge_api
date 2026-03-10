from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.metadata.workspace_metadata_backfill_service import WorkspaceMetadataBackfillService  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill workspace_table/workspace_column metadata from model_table/model_column."
    )
    parser.add_argument("--workspace-id", dest="workspace_id", default=None, help="Optional workspace scope")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Report changes without applying updates",
    )
    parser.add_argument(
        "--sample-limit",
        dest="sample_limit",
        type=int,
        default=25,
        help="Mismatch sample row limit (1-200)",
    )
    parser.add_argument(
        "--report-file",
        dest="report_file",
        default=None,
        help="Optional path to write JSON report",
    )
    return parser


def _write_report(path: str, report: Dict[str, Any]) -> None:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    args = _build_parser().parse_args()

    service = WorkspaceMetadataBackfillService()
    result = service.run(
        workspace_id=args.workspace_id,
        dry_run=bool(args.dry_run),
        sample_limit=int(args.sample_limit),
    )

    if args.report_file:
        _write_report(args.report_file, result)

    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=False))


if __name__ == "__main__":
    main()

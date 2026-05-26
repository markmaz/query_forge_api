from __future__ import annotations

import argparse
import json
from typing import Optional, Sequence

from app.services.feedback_learning import AnalysisBackfillService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill failure analyses for negative prompt feedback rows.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum feedback rows to inspect.")
    parser.add_argument(
        "--workspace-id",
        dest="workspace_id",
        default=None,
        help="Optional workspace filter.",
    )
    parser.add_argument(
        "--date-from",
        dest="date_from",
        default=None,
        help="Optional inclusive start timestamp/date.",
    )
    parser.add_argument(
        "--date-to",
        dest="date_to",
        default=None,
        help="Optional inclusive end timestamp/date.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Run live analysis. Default is dry-run.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    service = AnalysisBackfillService()
    result = service.backfill_negative_feedback(
        limit=args.limit,
        dry_run=(not bool(args.write)),
        workspace_id=args.workspace_id,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

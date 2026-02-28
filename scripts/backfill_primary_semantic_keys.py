from __future__ import annotations

import argparse
import json
import logging

from app.services.semantic.semantic_concept_service import SemanticConceptService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill model_column.semantic_concept_key/semantic_concept_id from primary concept-column mappings."
    )
    parser.add_argument("--workspace-id", dest="workspace_id", default=None, help="Optional workspace scope.")
    parser.add_argument("--vertical-norm", dest="vertical_norm", default=None, help="Optional vertical scope.")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Do not update rows; only report candidate count.",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    args = _build_parser().parse_args()
    result = SemanticConceptService().backfill_primary_semantic_keys(
        workspace_id=args.workspace_id,
        vertical_norm=args.vertical_norm,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

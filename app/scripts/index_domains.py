from __future__ import annotations

import argparse
import logging

from app.services.vector import DomainVectorIndexService

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or refresh Qdrant domain vector index.")
    parser.add_argument("--workspace-id", dest="workspace_id", default=None, help="Optional workspace scope.")
    parser.add_argument(
        "--vertical",
        dest="vertical_norm",
        default=None,
        help="Optional vertical filter (education|healthcare|generic).",
    )
    parser.add_argument(
        "--json-fallback",
        dest="json_fallback_path",
        default=None,
        help="Optional JSON fallback path when domain_profile query returns empty.",
    )
    parser.add_argument("--force", dest="force", action="store_true", help="Re-embed and upsert all domains.")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    svc = DomainVectorIndexService()
    result = svc.reindex_domains(
        workspace_id=args.workspace_id,
        vertical_norm=args.vertical_norm,
        force=bool(args.force),
        json_fallback_path=args.json_fallback_path,
    )
    logger.info("domain index result=%s", result)


if __name__ == "__main__":
    main()

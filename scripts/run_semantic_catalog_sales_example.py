from __future__ import annotations

import argparse
import json
import logging

from app.services.semantic.catalog.semantic_catalog_builder import SemanticCatalogBuilder


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Semantic Catalog Builder for Sales Performance domain")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--domain-id", required=True, type=int)
    parser.add_argument("--vertical", default="generic")
    parser.add_argument("--write", action="store_true", help="Persist catalog rows. Default is dry-run")
    args = parser.parse_args()

    builder = SemanticCatalogBuilder()
    result = builder.run_sales_performance_example(
        workspace_id=args.workspace_id,
        domain_id=args.domain_id,
        vertical_norm=args.vertical,
        dry_run=(not args.write),
    )

    print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

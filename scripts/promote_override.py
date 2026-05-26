from __future__ import annotations

import argparse
import json
from typing import Optional, Sequence

from app.services.feedback_learning import CatalogPromotionService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Promote a feedback-learning override into curated metadata.",
    )
    parser.add_argument(
        "--kind",
        choices=("semantic", "domain"),
        required=True,
        help="Override family to promote.",
    )
    parser.add_argument(
        "--override-id",
        type=int,
        required=True,
        help="Override id to promote.",
    )
    parser.add_argument(
        "--promoted-by",
        required=True,
        help="User id performing the promotion.",
    )
    parser.add_argument(
        "--notes",
        required=False,
        help="Optional audit note.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    service = CatalogPromotionService()
    if args.kind == "semantic":
        result = service.promote_semantic_override(
            override_id=int(args.override_id),
            promoted_by=str(args.promoted_by),
            notes=args.notes,
        )
    else:
        result = service.promote_domain_override(
            override_id=int(args.override_id),
            promoted_by=str(args.promoted_by),
            notes=args.notes,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

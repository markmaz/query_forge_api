#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.nlp.tier2_spacy.training.seed_from_registry import generate_seed_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weakly labeled Tier2 JSONL from semantic registry tables")
    parser.add_argument("--out", required=True, help="Output JSONL file")
    parser.add_argument("--vertical", default="generic", help="Vertical norm")
    parser.add_argument("--limit", type=int, default=500, help="Row limit per source query")
    args = parser.parse_args()

    result = generate_seed_jsonl(output_path=args.out, vertical_norm=args.vertical, limit=args.limit)
    print(f"Wrote {result.examples} examples to {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

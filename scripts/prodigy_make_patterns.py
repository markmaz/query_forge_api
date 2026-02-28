#!/usr/bin/env python3
"""
Generate Prodigy weak-label patterns for Tier2 entity annotation.

Usage:
  python3 scripts/prodigy_make_patterns.py --in data/seed_terms.json --out data/patterns_tier2.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _tokenize_phrase(phrase: str) -> List[Dict[str, str]]:
    tokens = [tok.strip() for tok in str(phrase or "").split() if tok.strip()]
    return [{"LOWER": token.lower()} for token in tokens]


def _iter_patterns(seed_terms: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for label, terms in seed_terms.items():
        if not isinstance(terms, list):
            continue
        for term in terms:
            text = str(term or "").strip()
            if text == "":
                continue
            pattern = _tokenize_phrase(text)
            if not pattern:
                continue
            yield {"label": str(label), "pattern": pattern}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Prodigy patterns JSONL from seed terms")
    parser.add_argument("--in", dest="input_path", required=True, help="Input seed terms JSON path")
    parser.add_argument("--out", dest="output_path", required=True, help="Output Prodigy patterns JSONL path")
    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output_path)

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("seed terms input must be a JSON object of label -> [terms]")

    patterns = list(_iter_patterns(payload))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in patterns:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(patterns)} patterns to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if text == "":
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON at line {idx}: {exc}") from exc
        if not isinstance(payload, dict):
            continue
        prompt = str(payload.get("text") or "")
        if prompt == "":
            continue
        if not isinstance(payload.get("entities"), list):
            payload["entities"] = []
        if not isinstance(payload.get("cats"), dict):
            payload["cats"] = {}
        if not isinstance(payload.get("meta"), dict):
            payload["meta"] = {}
        rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _dedupe_prefer_first(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        text = str(row.get("text") or "")
        if text in seen:
            continue
        seen.add(text)
        out.append(row)
    return out


def _split_rows(rows: List[Dict[str, Any]], *, seed: int, dev_ratio: float) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not rows:
        return [], []
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    dev_count = int(round(len(shuffled) * dev_ratio))
    if len(shuffled) >= 2:
        dev_count = max(1, min(len(shuffled) - 1, dev_count))
    else:
        dev_count = 0
    split_at = len(shuffled) - dev_count
    train_rows = shuffled[:split_at]
    dev_rows = shuffled[split_at:]
    return train_rows, dev_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge spaCy JSONL datasets and re-split into train/dev.")
    parser.add_argument("--base-train", required=True, help="Base train JSONL")
    parser.add_argument("--base-dev", required=True, help="Base dev JSONL")
    parser.add_argument("--extra", action="append", required=True, help="Extra spaCy JSONL file (repeatable)")
    parser.add_argument("--out-train", required=True, help="Output merged train JSONL")
    parser.add_argument("--out-dev", required=True, help="Output merged dev JSONL")
    parser.add_argument("--seed", type=int, default=13, help="Shuffle seed (default: 13)")
    parser.add_argument("--dev-ratio", type=float, default=0.10, help="Dev ratio (default: 0.10)")
    args = parser.parse_args()

    if args.dev_ratio <= 0.0 or args.dev_ratio >= 1.0:
        raise ValueError("--dev-ratio must be between 0 and 1")

    base_train = _load_jsonl(Path(args.base_train))
    base_dev = _load_jsonl(Path(args.base_dev))
    extras: List[Dict[str, Any]] = []
    for extra_path in args.extra:
        extras.extend(_load_jsonl(Path(extra_path)))

    # Prefer extra examples on duplicate text by putting extras first.
    merged = _dedupe_prefer_first([*extras, *base_train, *base_dev])
    train_rows, dev_rows = _split_rows(merged, seed=args.seed, dev_ratio=args.dev_ratio)

    _write_jsonl(Path(args.out_train), train_rows)
    _write_jsonl(Path(args.out_dev), dev_rows)

    print(
        "Merged dataset summary: "
        f"extras={len(extras)}, "
        f"base_train={len(base_train)}, "
        f"base_dev={len(base_dev)}, "
        f"deduped_total={len(merged)}, "
        f"train={len(train_rows)}, "
        f"dev={len(dev_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

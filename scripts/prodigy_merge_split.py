#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_text_key(text: str) -> str:
    return str(text or "").strip().lower()


def _extract_entities(example: Dict[str, Any], text_len: int) -> List[Dict[str, Any]]:
    spans = example.get("spans")
    if isinstance(spans, list):
        source = spans
    else:
        # Allow already-converted rows to pass through.
        source = example.get("entities") if isinstance(example.get("entities"), list) else []

    out: List[Dict[str, Any]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label == "":
            continue
        try:
            start = int(item.get("start"))
            end = int(item.get("end"))
        except Exception:
            continue
        if start < 0 or end <= start or end > text_len:
            continue
        out.append({"start": start, "end": end, "label": label})
    return out


def _extract_cats(example: Dict[str, Any]) -> Dict[str, float]:
    cats_raw = example.get("cats")
    if isinstance(cats_raw, dict):
        out: Dict[str, float] = {}
        for key, value in cats_raw.items():
            out[str(key)] = _safe_float(value, 0.0)
        return out

    label = example.get("label")
    if isinstance(label, str) and label.strip() != "":
        return {label.strip(): 1.0}
    return {}


def _extract_meta(example: Dict[str, Any], *, dataset_name: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}

    existing_meta = example.get("meta")
    if isinstance(existing_meta, dict):
        for key, value in existing_meta.items():
            meta[str(key)] = value

    for field in ("id", "source", "session", "_input_hash", "_task_hash"):
        if field in example and field not in meta:
            meta[field] = example[field]

    meta["dataset"] = dataset_name
    return meta


def _to_dataset_row(example: Dict[str, Any], *, dataset_name: str) -> Optional[Dict[str, Any]]:
    text = str(example.get("text") or "").strip()
    if text == "":
        return None

    entities = _extract_entities(example, len(text))
    cats = _extract_cats(example)
    meta = _extract_meta(example, dataset_name=dataset_name)
    return {
        "text": text,
        "entities": entities,
        "cats": cats,
        "meta": meta,
    }


def _iter_jsonl(path: Path) -> Iterable[Tuple[int, Dict[str, Any]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == "":
            continue
        try:
            payload = json.loads(stripped)
        except Exception:
            continue
        if isinstance(payload, dict):
            yield idx, payload


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def merge_and_split(
    *,
    in_dir: Path,
    train_out: Path,
    dev_out: Path,
    seed: int,
    dev_ratio: float,
) -> Dict[str, int]:
    files = sorted(in_dir.glob("*.jsonl"))
    if not files:
        raise FileNotFoundError(f"no JSONL files found under {in_dir}")

    total_read = 0
    kept = 0
    duplicates = 0
    invalid = 0

    rows: List[Dict[str, Any]] = []
    seen_text: set[str] = set()

    for path in files:
        dataset_name = path.stem
        for _, payload in _iter_jsonl(path):
            total_read += 1
            row = _to_dataset_row(payload, dataset_name=dataset_name)
            if row is None:
                invalid += 1
                continue

            key = _normalize_text_key(row["text"])
            if key in seen_text:
                duplicates += 1
                continue
            seen_text.add(key)
            rows.append(row)
            kept += 1

    rng = random.Random(int(seed))
    rng.shuffle(rows)

    if not rows:
        _write_jsonl(train_out, [])
        _write_jsonl(dev_out, [])
        return {
            "files": len(files),
            "total_read": total_read,
            "kept": kept,
            "duplicates": duplicates,
            "invalid": invalid,
            "train": 0,
            "dev": 0,
        }

    ratio = max(0.0, min(1.0, float(dev_ratio)))
    dev_count = int(len(rows) * ratio)
    if len(rows) > 10 and dev_count < 1:
        dev_count = 1
    dev_count = max(0, min(len(rows), dev_count))

    dev_rows = rows[:dev_count]
    train_rows = rows[dev_count:]

    _write_jsonl(train_out, train_rows)
    _write_jsonl(dev_out, dev_rows)

    return {
        "files": len(files),
        "total_read": total_read,
        "kept": kept,
        "duplicates": duplicates,
        "invalid": invalid,
        "train": len(train_rows),
        "dev": len(dev_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge Prodigy exported JSONL files and split into train/dev DatasetExample JSONL."
    )
    parser.add_argument("--in-dir", default="data/prodigy_exports", help="Input directory with *.jsonl files")
    parser.add_argument("--train", default="data/train.jsonl", help="Output train JSONL path")
    parser.add_argument("--dev", default="data/dev.jsonl", help="Output dev JSONL path")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic shuffle seed")
    parser.add_argument("--dev-ratio", type=float, default=0.1, help="Dev split ratio in [0, 1]")
    args = parser.parse_args()

    in_dir = Path(args.in_dir)
    train_out = Path(args.train)
    dev_out = Path(args.dev)

    if not in_dir.exists() or not in_dir.is_dir():
        print(f"ERROR: input directory does not exist or is not a directory: {in_dir}")
        return 2
    if args.dev_ratio < 0.0 or args.dev_ratio > 1.0:
        print("ERROR: --dev-ratio must be between 0 and 1.")
        return 2

    try:
        stats = merge_and_split(
            in_dir=in_dir,
            train_out=train_out,
            dev_out=dev_out,
            seed=args.seed,
            dev_ratio=args.dev_ratio,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    except Exception as exc:
        print(f"ERROR: merge/split failed: {exc}")
        return 1

    print("Merge/split complete")
    print(f"  files scanned: {stats['files']}")
    print(f"  total read: {stats['total_read']}")
    print(f"  kept: {stats['kept']}")
    print(f"  duplicates removed: {stats['duplicates']}")
    print(f"  invalid skipped: {stats['invalid']}")
    print(f"  train rows: {stats['train']} -> {train_out}")
    print(f"  dev rows: {stats['dev']} -> {dev_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

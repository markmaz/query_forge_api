#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


TYPE_TO_LABEL = {
    "school": "SCHOOL",
    "district": "DISTRICT",
}


DEFAULT_OUTPUT = "app/nlp/gazetteers/school_districts_patterns.jsonl"


def _norm_type(value: str) -> str:
    return (value or "").strip().lower()


def _norm_name(value: str) -> str:
    return " ".join((value or "").strip().split())


def _pattern_id(label: str, name: str) -> str:
    normalized_name = "_".join(name.lower().split())
    return f"{label}:{normalized_name}"


def _iter_records(reader: csv.DictReader) -> Iterable[Tuple[str, str]]:
    fieldnames = [str(x or "").strip() for x in (reader.fieldnames or [])]
    if not fieldnames:
        raise SystemExit("CSV has no header row")

    name_col = "name" if "name" in fieldnames else None
    type_col = "type" if "type" in fieldnames else None
    if not name_col or not type_col:
        raise SystemExit(f"CSV must have columns 'name' and 'type'. Found: {fieldnames}")

    for row in reader:
        if not isinstance(row, dict):
            continue
        name = _norm_name(row.get(name_col) or "")
        typ = _norm_type(row.get(type_col) or "")
        if not name:
            continue
        if typ not in TYPE_TO_LABEL:
            continue
        yield name, typ


def main() -> int:
    p = argparse.ArgumentParser(
        description="Build school/district gazetteer patterns for spaCy EntityRuler."
    )
    p.add_argument(
        "--in-csv",
        default="school_districts.csv",
        help="CSV with columns: name,type (default: school_districts.csv)",
    )
    p.add_argument(
        "--out",
        default=DEFAULT_OUTPUT,
        help=f"Output patterns JSONL path (default: {DEFAULT_OUTPUT})",
    )
    args = p.parse_args()

    src = Path(args.in_csv)
    out = Path(args.out)
    if not src.exists():
        raise SystemExit(f"Input CSV not found: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)

    seen = set()
    records: List[Dict[str, str]] = []
    rows_written = 0

    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for name, typ in _iter_records(reader):
            key = (name.lower(), typ)
            if key in seen:
                continue
            seen.add(key)
            label = TYPE_TO_LABEL[typ]
            records.append(
                {
                    "label": label,
                    "pattern": name,
                    "id": _pattern_id(label, name),
                }
            )

    with out.open("w", encoding="utf-8") as w:
        for rec in records:
            w.write(json.dumps(rec, ensure_ascii=False) + "\n")
            rows_written += 1

    print(f"Wrote {rows_written} patterns to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

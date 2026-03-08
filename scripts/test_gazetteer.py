#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import spacy  # noqa: E402

from app.nlp.gazetteers import add_school_district_ruler  # noqa: E402

DEFAULT_MODEL = "models/tier2/model-best"
DEFAULT_PATTERNS = "app/nlp/gazetteers/school_districts_patterns.jsonl"
DEFAULT_CSV = "school_districts.csv"


def _pick_sample_names(csv_path: Path) -> Tuple[Optional[str], Optional[str]]:
    if not csv_path.exists():
        return None, None
    district = None
    school = None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            typ = str(row.get("type") or "").strip().lower()
            if not name:
                continue
            if typ == "district" and district is None:
                district = name
            if typ == "school" and school is None:
                school = name
            if district and school:
                break
    return district, school


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test school/district gazetteer EntityRuler")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="spaCy model path")
    parser.add_argument("--patterns", default=DEFAULT_PATTERNS, help="Gazetteer patterns JSONL path")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Source CSV used to build gazetteer patterns")
    args = parser.parse_args()

    model_path = Path(args.model)
    patterns_path = Path(args.patterns)
    csv_path = Path(args.csv)

    if not model_path.exists():
        print(f"ERROR: model not found: {model_path}")
        return 2
    if not patterns_path.exists():
        print(f"ERROR: patterns not found: {patterns_path}")
        return 2

    district, school = _pick_sample_names(csv_path)
    if not district:
        district = "Metro Public Schools District"
    if not school:
        school = "Clarksville Elementary School"

    text = f"Show attendance for students in {district} and at {school} this year."

    nlp = spacy.load(str(model_path))
    add_school_district_ruler(nlp, patterns_path)
    doc = nlp(text)

    print(f"Prompt: {text}")
    if not doc.ents:
        print("No entities found.")
        return 0

    print("Entities:")
    for ent in doc.ents:
        print(f"- {ent.label_}: '{ent.text}' [{ent.start_char}:{ent.end_char}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


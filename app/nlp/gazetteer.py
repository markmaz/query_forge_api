from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

LABEL_BY_TYPE = {
    "school": "ORG_SCHOOL",
    "district": "ORG_DISTRICT",
}


def load_school_district_patterns(csv_path: str) -> List[Dict[str, Any]]:
    path = Path(str(csv_path or "").strip())
    if not path.exists():
        return []

    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = str((raw or {}).get("name") or "").strip()
            type_raw = str((raw or {}).get("type") or "").strip().lower()
            if name == "" or type_raw not in LABEL_BY_TYPE:
                continue
            rows.append({"name": name, "type": type_raw})

    dedup: Dict[tuple[str, str], Dict[str, str]] = {}
    for row in rows:
        key = (row["name"].lower(), row["type"])
        if key not in dedup:
            dedup[key] = row

    ordered = sorted(
        dedup.values(),
        key=lambda row: (len(row["name"]), row["name"].lower()),
        reverse=True,
    )
    patterns: List[Dict[str, Any]] = []
    for row in ordered:
        name = row["name"]
        label = LABEL_BY_TYPE[row["type"]]
        tokens = [part for part in name.split() if part]
        if not tokens:
            continue
        patterns.append(
            {
                "label": label,
                "pattern": [{"LOWER": token.lower()} for token in tokens],
                "id": name,
            }
        )
    return patterns


def build_entity_ruler(nlp: Any, patterns: List[Dict[str, Any]]) -> Any:
    if "entity_ruler" in getattr(nlp, "pipe_names", []):
        ruler = nlp.get_pipe("entity_ruler")
    else:
        if "ner" in getattr(nlp, "pipe_names", []):
            ruler = nlp.add_pipe("entity_ruler", before="ner", config={"phrase_matcher_attr": "LOWER"})
        else:
            ruler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})

    if patterns:
        ruler.add_patterns(patterns)

    if "ner" in getattr(nlp, "pipe_names", []):
        ner = nlp.get_pipe("ner")
        if hasattr(ner, "overwrite_ents"):
            try:
                ner.overwrite_ents = False
            except Exception:
                pass
    return ruler

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _dataset_name_from_path(path: Path) -> str:
    name = path.stem
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")]
    return name or "prodigy_dataset"


def _iter_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if text == "":
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {idx}: {exc}") from exc
        if not isinstance(payload, dict):
            continue
        rows.append(payload)
    return rows


def _valid_entities(text: str, spans: Any) -> Tuple[List[Dict[str, Any]], int]:
    entities: List[Dict[str, Any]] = []
    dropped = 0
    if not isinstance(spans, list):
        return entities, dropped

    for span in spans:
        if not isinstance(span, dict):
            dropped += 1
            continue
        start_raw = span.get("start")
        end_raw = span.get("end")
        label = str(span.get("label") or "").strip()
        if start_raw is None or end_raw is None or label == "":
            dropped += 1
            continue
        try:
            start = int(start_raw)
            end = int(end_raw)
        except Exception:
            dropped += 1
            continue
        if start < 0 or end <= start or end > len(text):
            dropped += 1
            continue
        entities.append({"start": start, "end": end, "label": label})

    entities.sort(key=lambda item: (int(item["start"]), int(item["end"]), str(item["label"])))
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for entity in entities:
        key = (entity["start"], entity["end"], entity["label"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)
    return deduped, dropped


def _build_output_row(payload: Dict[str, Any], *, dataset_name: str) -> Tuple[Dict[str, Any] | None, int]:
    text = str(payload.get("text") or "")
    if text == "":
        return None, 0

    entities, dropped = _valid_entities(text, payload.get("spans"))
    cats = payload.get("cats") if isinstance(payload.get("cats"), dict) else {}
    meta = dict(payload.get("meta") or {})
    meta["dataset"] = dataset_name
    if "source" not in meta:
        meta["source"] = "prodigy_db_out"

    row = {
        "text": text,
        "entities": entities,
        "cats": cats,
        "meta": meta,
    }
    return row, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Prodigy NER db-out JSONL into spaCy training JSONL.")
    parser.add_argument("--in", dest="input_path", required=True, help="Input Prodigy db-out JSONL path")
    parser.add_argument("--out", dest="output_path", required=True, help="Output spaCy-format JSONL path")
    parser.add_argument("--dataset", default=None, help="Dataset name override for meta.dataset")
    args = parser.parse_args()

    src = Path(args.input_path)
    if not src.exists():
        raise FileNotFoundError(f"Input file not found: {src}")
    dataset_name = str(args.dataset or _dataset_name_from_path(src)).strip()
    if dataset_name == "":
        dataset_name = "prodigy_dataset"

    rows = _iter_jsonl(src)
    converted: List[Dict[str, Any]] = []
    dropped_spans = 0
    for payload in rows:
        out_row, dropped = _build_output_row(payload, dataset_name=dataset_name)
        dropped_spans += dropped
        if out_row is None:
            continue
        converted.append(out_row)

    dst = Path(args.output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as handle:
        for row in converted:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"Wrote {len(converted)} examples to {dst} "
        f"(dataset={dataset_name}, dropped_spans={dropped_spans})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

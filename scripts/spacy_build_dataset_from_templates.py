#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.nlp.tier2_spacy.training.dataset import DatasetEntity, DatasetExample, write_jsonl  # noqa: E402

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")
_NORMALIZE_RE = re.compile(r"[^A-Za-z0-9_]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")

_PLACEHOLDER_VALUES: Dict[str, str] = {
    "dimension": "school",
    "grade_level": "grade",
    "year": "this year",
    "subgroup": "English Learners",
    "program": "EL",
    "assessment_type": "state assessment",
    "subject": "math",
    "reason": "transfer",
    "location": "classroom",
    "intervention": "tier 2 intervention",
    "timeframe": "last month",
}


def _normalize_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = _NORMALIZE_RE.sub("_", text)
    text = _MULTI_UNDERSCORE_RE.sub("_", text).strip("_")
    return text or "unknown"


def _normalize_category_key(value: Any) -> str:
    text = str(value or "").strip()
    text = _NORMALIZE_RE.sub("_", text)
    text = _MULTI_UNDERSCORE_RE.sub("_", text).strip("_")
    return text or "Unknown"


def _choose_split(raw_split: Any, *, record_id: Any, text_for_hash: str) -> str:
    split = str(raw_split or "").strip().lower()
    if split in {"train", "dev"}:
        return split
    base = f"{record_id}|{text_for_hash}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 10
    return "train" if bucket < 9 else "dev"


def _expand_template_text(text: str) -> Tuple[str, List[DatasetEntity]]:
    source = str(text or "")
    out_parts: List[str] = []
    entities: List[DatasetEntity] = []
    cursor = 0
    out_len = 0

    for match in _PLACEHOLDER_RE.finditer(source):
        out_parts.append(source[cursor : match.start()])
        out_len += len(source[cursor : match.start()])

        var_name = str(match.group(1) or "").strip()
        replacement = _PLACEHOLDER_VALUES.get(var_name, "value")
        start = out_len
        end = start + len(replacement)
        out_parts.append(replacement)
        out_len = end
        entities.append(DatasetEntity(start=start, end=end, label="TEMPLATE_VAR"))
        cursor = match.end()

    tail = source[cursor:]
    out_parts.append(tail)
    expanded = "".join(out_parts)
    return expanded, entities


def _build_cats(payload: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    out[_normalize_label(payload.get("label"))] = 1.0
    category = payload.get("category")
    if str(category or "").strip():
        out[f"CAT__{_normalize_category_key(category)}"] = 1.0
    return out


def _iter_jsonl_paths(*, in_dir: Optional[str], globs: Sequence[str]) -> List[Path]:
    paths: List[Path] = []
    if in_dir:
        root = Path(in_dir)
        if not root.exists():
            raise FileNotFoundError(f"input directory does not exist: {in_dir}")
        paths.extend(sorted(root.rglob("*.jsonl")))
    for pattern in globs:
        paths.extend(sorted(Path().glob(pattern)))
    dedup: Dict[str, Path] = {}
    for path in paths:
        if path.is_file():
            dedup[str(path.resolve())] = path
    return sorted(dedup.values(), key=lambda p: str(p))


def _iter_template_records(path: Path) -> Iterable[Dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == "":
            continue
        try:
            payload = json.loads(stripped)
        except Exception as exc:
            print(f"WARN {path}:{idx} invalid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            print(f"WARN {path}:{idx} JSON root is not an object; skipping")
            continue
        yield payload


def build_dataset_from_templates(
    *,
    in_dir: Optional[str],
    globs: Sequence[str],
    train_out: str,
    dev_out: str,
) -> Dict[str, int]:
    files = _iter_jsonl_paths(in_dir=in_dir, globs=globs)
    if not files:
        raise FileNotFoundError("no template JSONL files found from provided inputs")

    train_rows: List[DatasetExample] = []
    dev_rows: List[DatasetExample] = []
    seen_train: set[str] = set()
    seen_dev: set[str] = set()

    stats = {
        "files": len(files),
        "records_total": 0,
        "records_emitted": 0,
        "dedup_dropped": 0,
        "train": 0,
        "dev": 0,
    }

    for path in files:
        for payload in _iter_template_records(path):
            stats["records_total"] += 1
            original_text = str(payload.get("text") or "").strip()
            if original_text == "":
                continue

            expanded_text, entities = _expand_template_text(original_text)
            cats = _build_cats(payload)
            split = _choose_split(
                payload.get("split"),
                record_id=payload.get("id"),
                text_for_hash=expanded_text,
            )
            meta = {
                "id": payload.get("id"),
                "source": payload.get("source"),
                "category": payload.get("category"),
                "template_vars": payload.get("template_vars") or [],
            }
            example = DatasetExample(
                text=expanded_text,
                entities=entities,
                cats=cats,
                meta=meta,
            )

            if split == "dev":
                if example.text in seen_dev:
                    stats["dedup_dropped"] += 1
                    continue
                seen_dev.add(example.text)
                dev_rows.append(example)
                stats["dev"] += 1
            else:
                if example.text in seen_train:
                    stats["dedup_dropped"] += 1
                    continue
                seen_train.add(example.text)
                train_rows.append(example)
                stats["train"] += 1
            stats["records_emitted"] += 1

    write_jsonl(train_out, train_rows)
    write_jsonl(dev_out, dev_rows)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Tier2 train/dev datasets from template JSONL corpus")
    parser.add_argument("--in-dir", help="Directory containing template JSONL files (recursive)")
    parser.add_argument(
        "--glob",
        action="append",
        default=[],
        help="Glob pattern for template JSONL files (can be repeated)",
    )
    parser.add_argument("--train-out", required=True, help="Output train JSONL path")
    parser.add_argument("--dev-out", required=True, help="Output dev JSONL path")
    args = parser.parse_args()

    if not args.in_dir and not args.glob:
        parser.error("provide at least one of --in-dir or --glob")

    stats = build_dataset_from_templates(
        in_dir=args.in_dir,
        globs=args.glob,
        train_out=args.train_out,
        dev_out=args.dev_out,
    )
    print(
        "Built dataset "
        f"(files={stats['files']}, records_total={stats['records_total']}, "
        f"records_emitted={stats['records_emitted']}, train={stats['train']}, "
        f"dev={stats['dev']}, dedup_dropped={stats['dedup_dropped']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

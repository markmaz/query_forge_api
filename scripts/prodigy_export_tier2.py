#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.nlp.tier2_spacy.training.dataset import DatasetEntity, DatasetExample, write_jsonl  # noqa: E402

ALLOWED_ENTITY_LABELS = {"SUBGROUP", "DIMENSION", "TIME_RANGE", "METRIC"}
DEFAULT_TOPICS_PATH = "data/topics.json"
DEFAULT_DB_OUT = "data/prodigy_exports"

_NORMALIZE_RE = re.compile(r"[^A-Za-z0-9]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


class DatasetNotFoundError(RuntimeError):
    pass


def _normalize_topic(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = _NORMALIZE_RE.sub("_", text)
    text = _MULTI_UNDERSCORE_RE.sub("_", text).strip("_")
    if text.startswith("TOPIC_"):
        text = text[6:]
    return text


def _topic_key(value: Any) -> str:
    normalized = _normalize_topic(value)
    return f"TOPIC_{normalized}" if normalized else ""


def _load_topics(path: str) -> List[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_topics = payload.get("topics") or []
    elif isinstance(payload, list):
        raw_topics = payload
    else:
        raise ValueError("topics file must be a JSON list or {\"topics\": [...]} object")

    topics: List[str] = []
    for item in raw_topics:
        key = _topic_key(item)
        if key and key not in topics:
            topics.append(key)
    if not topics:
        raise ValueError("topics file did not contain any valid topic labels")
    return topics


def _topic_alias_map(topic_keys: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in topic_keys:
        out[key] = key
        plain = key[6:] if key.startswith("TOPIC_") else key
        out[plain] = key
    return out


def _extract_topic(example: Dict[str, Any], topic_alias: Dict[str, str]) -> Optional[str]:
    meta = example.get("meta")
    meta_dict = meta if isinstance(meta, dict) else {}
    candidates = [
        meta_dict.get("topic"),
        meta_dict.get("label"),
        meta_dict.get("category"),
        example.get("topic"),
        example.get("label"),
        example.get("category"),
    ]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            value = value[0]
        key = _topic_key(value)
        if key in topic_alias:
            return topic_alias[key]
        plain = _normalize_topic(value)
        if plain in topic_alias:
            return topic_alias[plain]
    return None


def _build_cats(topic_key: Optional[str], all_topic_keys: Sequence[str]) -> Dict[str, float]:
    if not topic_key:
        return {}
    return {key: (1.0 if key == topic_key else 0.0) for key in all_topic_keys}


def _extract_entities(text: str, spans: Any) -> List[DatasetEntity]:
    source = str(text or "")
    out: List[DatasetEntity] = []
    if not isinstance(spans, list):
        return out
    for span in spans:
        if not isinstance(span, dict):
            continue
        label = str(span.get("label") or "").strip().upper()
        if label not in ALLOWED_ENTITY_LABELS:
            continue
        try:
            start = int(span.get("start"))
            end = int(span.get("end"))
        except Exception:
            continue
        if start < 0 or end <= start or end > len(source):
            continue
        out.append(DatasetEntity(start=start, end=end, label=label))
    return out


def _prodigy_db_path() -> Path:
    prodigy_home = os.environ.get("PRODIGY_HOME", "").strip()
    if prodigy_home:
        home_path = Path(prodigy_home).expanduser()
        if home_path.suffix == ".db":
            return home_path
        return home_path / "prodigy.db"
    return Path.home() / ".prodigy" / "prodigy.db"


def _load_with_prodigy(dataset_name: str) -> List[Dict[str, Any]]:
    try:
        from prodigy.components.db import connect
    except Exception:
        return []
    db = connect()
    datasets = set(db.datasets) if hasattr(db, "datasets") else set()
    if datasets and dataset_name not in datasets:
        raise DatasetNotFoundError(f"Prodigy dataset '{dataset_name}' not found. Available: {sorted(datasets)}")
    rows = db.get_dataset(dataset_name) or []
    if not rows and datasets and dataset_name in datasets:
        return []
    if not rows and not datasets:
        # Unknown datasets list; if get_dataset returned empty, treat as missing.
        raise DatasetNotFoundError(f"Prodigy dataset '{dataset_name}' not found or empty.")
    return [row for row in rows if isinstance(row, dict)]


def _query_sqlite(conn: sqlite3.Connection, query: str, params: Tuple[Any, ...]) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    return cur.fetchall()


def _sqlite_try_queries(
    conn: sqlite3.Connection,
    queries: Sequence[Tuple[str, Tuple[Any, ...]]],
) -> Optional[List[sqlite3.Row]]:
    for query, params in queries:
        try:
            return _query_sqlite(conn, query, params)
        except sqlite3.OperationalError:
            continue
    return None


def _load_with_sqlite_fallback(dataset_name: str) -> List[Dict[str, Any]]:
    db_path = _prodigy_db_path()
    if not db_path.exists():
        raise DatasetNotFoundError(
            f"Prodigy dataset '{dataset_name}' not found. Also could not find fallback DB at {db_path}"
        )

    conn = sqlite3.connect(str(db_path))
    try:
        dataset_rows = _sqlite_try_queries(
            conn,
            [
                ("SELECT id FROM dataset WHERE name = ?", (dataset_name,)),
                ("SELECT id FROM Dataset WHERE name = ?", (dataset_name,)),
            ],
        )
        if not dataset_rows:
            raise DatasetNotFoundError(
                f"Prodigy dataset '{dataset_name}' not found in sqlite DB {db_path}"
            )
        dataset_id = int(dataset_rows[0]["id"])

        example_rows = _sqlite_try_queries(
            conn,
            [
                (
                    """
                    SELECT e.content AS content
                    FROM example e
                    JOIN link l ON l.example_id = e.id
                    WHERE l.dataset_id = ?
                    ORDER BY e.id
                    """,
                    (dataset_id,),
                ),
                (
                    """
                    SELECT e.content AS content
                    FROM Example e
                    JOIN Link l ON l.example_id = e.id
                    WHERE l.dataset_id = ?
                    ORDER BY e.id
                    """,
                    (dataset_id,),
                ),
            ],
        )
        if not example_rows:
            return []

        out: List[Dict[str, Any]] = []
        for row in example_rows:
            content = row["content"]
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            if not isinstance(content, str):
                continue
            try:
                payload = json.loads(content)
            except Exception:
                continue
            if isinstance(payload, dict):
                out.append(payload)
        return out
    finally:
        conn.close()


def _load_prodigy_examples(dataset_name: str) -> List[Dict[str, Any]]:
    try:
        return _load_with_prodigy(dataset_name)
    except DatasetNotFoundError:
        raise
    except Exception:
        # Prodigy import/runtime issues: fallback to sqlite.
        return _load_with_sqlite_fallback(dataset_name)


def _convert_examples(
    *,
    raw_examples: Sequence[Dict[str, Any]],
    all_topic_keys: Sequence[str],
    topic_alias: Dict[str, str],
) -> Tuple[List[DatasetExample], Counter[str], int]:
    converted: List[DatasetExample] = []
    entity_counts: Counter[str] = Counter()
    with_topic = 0

    for example in raw_examples:
        text = str(example.get("text") or "").strip()
        if text == "":
            continue
        entities = _extract_entities(text, example.get("spans"))
        for ent in entities:
            entity_counts[ent.label] += 1

        topic_key = _extract_topic(example, topic_alias)
        cats = _build_cats(topic_key, all_topic_keys)
        if cats:
            with_topic += 1

        meta = {
            "prodigy_id": example.get("_input_hash") or example.get("id"),
            "task_hash": example.get("_task_hash"),
            "topic": topic_key,
            "source": (example.get("meta") or {}).get("source") if isinstance(example.get("meta"), dict) else None,
        }
        converted.append(
            DatasetExample(
                text=text,
                entities=entities,
                cats=cats,
                meta=meta,
            )
        )

    return converted, entity_counts, with_topic


def _split_examples(
    examples: Sequence[DatasetExample],
    *,
    train_ratio: float,
    seed: int,
) -> Tuple[List[DatasetExample], List[DatasetExample]]:
    rows = list(examples)
    rng = random.Random(seed)
    rng.shuffle(rows)
    cut = int(len(rows) * train_ratio)
    cut = max(0, min(len(rows), cut))
    return rows[:cut], rows[cut:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Prodigy NER dataset to Tier2 spaCy training JSONL")
    parser.add_argument("--dataset", required=True, help="Prodigy dataset name")
    parser.add_argument(
        "--db-out",
        default=DEFAULT_DB_OUT,
        help="Output directory for exported JSONL snapshot copies",
    )
    parser.add_argument(
        "--topics",
        default=DEFAULT_TOPICS_PATH,
        help="Path to JSON file containing all topic labels",
    )
    parser.add_argument("--split", type=float, default=0.9, help="Train split ratio (0..1)")
    parser.add_argument("--seed", type=int, default=13, help="Random seed for deterministic shuffle")
    args = parser.parse_args()

    if args.split <= 0.0 or args.split >= 1.0:
        raise ValueError("--split must be between 0 and 1 (exclusive)")

    topics = _load_topics(args.topics)
    topic_alias = _topic_alias_map(topics)

    try:
        raw = _load_prodigy_examples(args.dataset)
    except DatasetNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2

    converted, entity_counts, with_topic = _convert_examples(
        raw_examples=raw,
        all_topic_keys=topics,
        topic_alias=topic_alias,
    )
    train_rows, dev_rows = _split_examples(converted, train_ratio=args.split, seed=args.seed)

    train_path = Path("data/train.jsonl")
    dev_path = Path("data/dev.jsonl")
    write_jsonl(str(train_path), train_rows)
    write_jsonl(str(dev_path), dev_rows)

    db_out = Path(args.db_out)
    db_out.mkdir(parents=True, exist_ok=True)
    write_jsonl(str(db_out / f"{args.dataset}_train.jsonl"), train_rows)
    write_jsonl(str(db_out / f"{args.dataset}_dev.jsonl"), dev_rows)

    print(f"Exported dataset: {args.dataset}")
    print(f"num examples: {len(converted)}")
    print(f"train examples: {len(train_rows)}")
    print(f"dev examples: {len(dev_rows)}")
    print(f"entity label counts: {dict(entity_counts)}")
    print(f"examples with topics: {with_topic}")
    print(f"examples without topics: {len(converted) - with_topic}")
    print(f"wrote {train_path} and {dev_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

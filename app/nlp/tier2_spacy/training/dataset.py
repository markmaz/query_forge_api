from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class DatasetEntity:
    start: int
    end: int
    label: str


@dataclass
class DatasetExample:
    text: str
    entities: List[DatasetEntity]
    cats: Dict[str, float]
    meta: Dict[str, Any]


def parse_jsonl_line(line: str) -> DatasetExample:
    payload = json.loads(line)
    text = str(payload.get("text") or "")
    if text.strip() == "":
        raise ValueError("dataset line requires non-empty text")

    entities_raw = payload.get("entities") or []
    entities: List[DatasetEntity] = []
    for item in entities_raw:
        start = int(item.get("start"))
        end = int(item.get("end"))
        label = str(item.get("label") or "").strip()
        if start < 0 or end <= start or end > len(text):
            raise ValueError(f"invalid entity offsets: start={start} end={end} len={len(text)}")
        if label == "":
            raise ValueError("entity label is required")
        entities.append(DatasetEntity(start=start, end=end, label=label))

    cats_raw = payload.get("cats") or {}
    cats: Dict[str, float] = {}
    for key, value in dict(cats_raw).items():
        cats[str(key)] = float(value)

    meta = dict(payload.get("meta") or {})
    return DatasetExample(text=text, entities=entities, cats=cats, meta=meta)


def load_jsonl(path: str) -> List[DatasetExample]:
    rows: List[DatasetExample] = []
    src = Path(path)
    for idx, line in enumerate(src.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped == "":
            continue
        try:
            rows.append(parse_jsonl_line(stripped))
        except DATASET_PARSE_ERRORS as exc:
            raise ValueError(f"invalid JSONL at line {idx}: {exc}") from exc
    return rows


def write_jsonl(path: str, examples: Iterable[DatasetExample]) -> None:
    dst = Path(path)
    lines: List[str] = []
    for example in examples:
        lines.append(
            json.dumps(
                {
                    "text": example.text,
                    "entities": [
                        {"start": ent.start, "end": ent.end, "label": ent.label}
                        for ent in example.entities
                    ],
                    "cats": example.cats,
                    "meta": example.meta,
                },
                ensure_ascii=False,
            )
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def to_docbin(*, jsonl_path: str, output_path: str, lang: str = "en") -> int:
    try:
        import spacy
        from spacy.tokens import DocBin
    except ImportError as exc:
        raise RuntimeError("spaCy is required to create DocBin") from exc

    nlp = spacy.blank(lang)
    docbin = DocBin(store_user_data=True)

    examples = load_jsonl(jsonl_path)
    for example in examples:
        doc = nlp.make_doc(example.text)
        spans = []
        for ent in example.entities:
            span = doc.char_span(ent.start, ent.end, label=ent.label, alignment_mode="contract")
            if span is None:
                continue
            spans.append(span)
        doc.ents = spans
        doc.cats = {k: float(v) for k, v in example.cats.items()}
        docbin.add(doc)

    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    docbin.to_disk(dst)
    return len(examples)


def try_extract_text_span(text: str, phrase: str) -> Optional[DatasetEntity]:
    source = str(text or "")
    token = str(phrase or "").strip()
    if source == "" or token == "":
        return None
    start = source.lower().find(token.lower())
    if start < 0:
        return None
    return DatasetEntity(start=start, end=start + len(token), label="VALUE_LITERAL")
DATASET_PARSE_ERRORS = (json.JSONDecodeError, TypeError, ValueError)

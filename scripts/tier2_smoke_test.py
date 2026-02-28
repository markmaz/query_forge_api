#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List, Tuple


def _load_prompts(path: str) -> List[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    for line in lines:
        text = line.strip()
        if text == "" or text.startswith("#"):
            continue
        out.append(text)
    return out


def _top_cats(cats: dict, *, threshold: float = 0.2, limit: int = 3) -> List[Tuple[str, float]]:
    rows = [(str(k), float(v)) for k, v in dict(cats or {}).items()]
    rows.sort(key=lambda item: item[1], reverse=True)
    return [(k, v) for k, v in rows if v >= threshold][:limit]


def _iter_entities(doc) -> Iterable[Tuple[str, str, int, int]]:
    for ent in list(getattr(doc, "ents", []) or []):
        yield (str(ent.label_), str(ent.text), int(ent.start_char), int(ent.end_char))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Tier2 spaCy model on sample prompts")
    parser.add_argument("--model", default="models/tier2/model-best", help="Model path")
    parser.add_argument("--prompts", default="data/smoke_prompts.txt", help="Prompt file (one per line)")
    args = parser.parse_args()

    try:
        import spacy
    except Exception as exc:
        raise RuntimeError("spaCy is required for smoke test") from exc

    model_path = Path(args.model)
    prompts_path = Path(args.prompts)
    if not model_path.exists():
        raise FileNotFoundError(f"model path not found: {model_path}")
    if not prompts_path.exists():
        raise FileNotFoundError(f"prompts file not found: {prompts_path}")

    nlp = spacy.load(str(model_path))
    prompts = _load_prompts(str(prompts_path))
    if not prompts:
        print(f"No prompts found in {prompts_path}")
        return 0

    for idx, prompt in enumerate(prompts, start=1):
        doc = nlp(prompt)
        print(f"[{idx}] Prompt: {prompt}")

        top_topics = _top_cats(getattr(doc, "cats", {}), threshold=0.2, limit=3)
        if top_topics:
            topic_text = ", ".join(f"{label}={score:.3f}" for label, score in top_topics)
            print(f"  Topics: {topic_text}")
        else:
            print("  Topics: (none above 0.2)")

        entities = list(_iter_entities(doc))
        if entities:
            print("  Entities:")
            for label, text, start, end in entities:
                print(f"    - {label}: '{text}' [{start}:{end}]")
        else:
            print("  Entities: (none)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

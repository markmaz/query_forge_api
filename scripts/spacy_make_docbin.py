#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.nlp.tier2_spacy.training.dataset import load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Tier2 JSONL training data to spaCy DocBin")
    parser.add_argument("--in", dest="input_path", required=True, help="Input JSONL file")
    parser.add_argument("--out", dest="output_path", required=True, help="Output .spacy file")
    parser.add_argument("--lang", default="en", help="spaCy language code")
    args = parser.parse_args()

    try:
        import spacy
        from spacy.tokens import DocBin
    except Exception as exc:
        raise RuntimeError("spaCy is required to create DocBin") from exc

    nlp = spacy.blank(args.lang)
    docbin = DocBin(store_user_data=True)
    examples = load_jsonl(args.input_path)

    total_examples = 0
    total_entities = 0
    dropped_entities = 0
    examples_with_zero_entities = 0

    for example in examples:
        total_examples += 1
        doc = nlp.make_doc(example.text)
        spans = []

        for ent in example.entities:
            total_entities += 1
            span = doc.char_span(ent.start, ent.end, label=ent.label, alignment_mode="contract")
            if span is None:
                span = doc.char_span(ent.start, ent.end, label=ent.label, alignment_mode="expand")
            if span is None:
                dropped_entities += 1
                preview = example.text.replace("\n", " ")
                if len(preview) > 160:
                    preview = preview[:157] + "..."
                print(
                    f"WARN dropped entity span label={ent.label} start={ent.start} end={ent.end} text='{preview}'"
                )
                continue
            spans.append(span)

        doc.ents = spans
        doc.cats = {k: float(v) for k, v in example.cats.items()}
        docbin.add(doc)
        if not spans:
            examples_with_zero_entities += 1

    output = Path(args.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    docbin.to_disk(output)

    print(f"Wrote {total_examples} examples to {args.output_path}")
    print(
        "DocBin stats: "
        f"total_examples={total_examples}, "
        f"total_ents={total_entities}, "
        f"dropped_ents={dropped_entities}, "
        f"examples_with_zero_ents={examples_with_zero_entities}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations
import argparse
from collections import Counter
import spacy
from spacy.tokens import DocBin

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--lang", default="en")
    args = ap.parse_args()

    nlp = spacy.blank(args.lang)
    db = DocBin().from_disk(args.path)
    docs = list(db.get_docs(nlp.vocab))

    ent_count = 0
    ent_labels = Counter()
    cat_keys = Counter()
    docs_with_cats = 0

    for d in docs:
        ent_count += len(d.ents)
        for e in d.ents:
            ent_labels[e.label_] += 1
        if d.cats:
            docs_with_cats += 1
            for k in d.cats.keys():
                cat_keys[k] += 1

    print("Docs:", len(docs))
    print("Total ents:", ent_count)
    print("Ent labels:", ent_labels)
    print("Docs w/ cats:", docs_with_cats)
    print("Cat keys seen:", list(cat_keys.keys())[:50])

    if len(docs) > 0:
        ratio = docs_with_cats / len(docs)
        if ratio < 0.10:
            print(
                f"WARNING: Cats present in only {docs_with_cats}/{len(docs)} docs — "
                "textcat training may be unreliable."
            )

if __name__ == "__main__":
    main()

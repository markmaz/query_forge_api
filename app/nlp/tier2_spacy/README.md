# Tier2 spaCy Training

Use these commands to run the Tier2 pipeline end-to-end:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install "spacy>=3.7,<3.8" spacy-transformers torch
python -m spacy validate
spacy project run train
```

Notes:
- Run from the repository root where `project.yml` lives.
- `spacy project run train` executes:
  1. `build-dataset`
  2. `make-train-docbin`
  3. `make-dev-docbin`
  4. `train-tier2`

## Phase 1 Focus (NER-only)
- We are intentionally training NER-only first until `ENTS_F >= 0.80`.
- Train command:

```bash
python3 scripts/spacy_train_tier2.py --train data/train.spacy --dev data/dev.spacy --output models/tier2_ner --gpu -1
```

- Primary metric to watch: `ENTS_F`.

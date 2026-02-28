# Ratio Metric Improvement Loop

This loop adds targeted ratio prompts, labels them in Prodigy, converts to spaCy JSONL, merges into train/dev, and retrains the NER model.

## 1) Generate unlabeled ratio prompts

```bash
python3 scripts/gen_ratio_prompts.py --out data/ratio_unlabeled.jsonl --count 200 --seed 13
```

## 2) Label in Prodigy (`ner.correct`)

Example command (adjust model path/labels as needed):

```bash
python3 -m prodigy ner.correct planner_ratio_v1 models/tier2_ner_v1_stable data/ratio_unlabeled.jsonl --label METRIC,DIMENSION,TIME_RANGE,SUBGROUP,ORG_SCHOOL,ORG_DISTRICT
```

## 3) Export labeled dataset from Prodigy

```bash
mkdir -p data/prodigy
python3 -m prodigy db-out planner_ratio_v1 > data/prodigy/planner_ratio_v1.jsonl
```

## 4) Convert Prodigy JSONL to spaCy training JSONL

```bash
python3 scripts/convert_prodigy_ner_to_spacy_jsonl.py \
  --in data/prodigy/planner_ratio_v1.jsonl \
  --out data/prodigy/planner_ratio_v1.spacy.jsonl \
  --dataset planner_ratio_v1
```

## 5) Merge with existing train/dev and re-split (90/10, seed=13)

```bash
python3 scripts/merge_spacy_jsonl.py \
  --base-train data/train.jsonl \
  --base-dev data/dev.jsonl \
  --extra data/prodigy/planner_ratio_v1.spacy.jsonl \
  --out-train data/train.jsonl \
  --out-dev data/dev.jsonl \
  --seed 13 \
  --dev-ratio 0.10
```

## 6) Rebuild DocBins

```bash
python3 scripts/spacy_make_docbin.py --in data/train.jsonl --out data/train.spacy
python3 scripts/spacy_make_docbin.py --in data/dev.jsonl --out data/dev.spacy
```

## 7) Retrain

```bash
python3 scripts/spacy_train_tier2.py \
  --config app/nlp/tier2_spacy/config/config_ner_only.cfg \
  --train data/train.spacy \
  --dev data/dev.spacy \
  --output models/tier2_ratio_loop \
  --cpu-only
```

## Notes

- This loop is statistical-only and does not add deterministic EntityRuler rules.
- You can pass multiple `--extra` files to `scripts/merge_spacy_jsonl.py`.

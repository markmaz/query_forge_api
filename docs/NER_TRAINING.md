# NER Training (Tier2)

## How To Run
1. `cd "/Users/mmaslak/Local Documents/projects/query-forge-api"`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -U pip`
4. `pip install "spacy>=3.7,<3.8" spacy-transformers torch`
5. `python -m spacy validate`
6. `spacy project run make-patterns`
7. `spacy project run ner-train`

## Notes
- `ner-train` runs: `export-prodigy -> make-train-docbin -> make-dev-docbin -> train-tier2 -> smoke-test`.
- Default Prodigy dataset: `qf_tier2_ner_v1`. Override in `project.yml` var `prodigy_dataset` if needed.

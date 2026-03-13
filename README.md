aws codeartifact login --tool pip --domain kytheralabs --domain-owner 120626691517 --repository cohort-ai --region us-east-1 
## Linting

Run Ruff:

```
./scripts/lint.sh
```

Pre-commit hook:

```
pre-commit install
```
celery -A app.celery_app worker --loglevel=INFO --pool=solo --concurrency=1

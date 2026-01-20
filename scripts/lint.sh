#!/usr/bin/env bash
set -euo pipefail

if [ -x .venv/bin/ruff ]; then
  .venv/bin/ruff check .
else
  ruff check .
fi

if [ -x .venv/bin/pytest ]; then
  .venv/bin/pytest -q --cov=app --cov-report=term-missing
else
  pytest -q --cov=app --cov-report=term-missing
fi

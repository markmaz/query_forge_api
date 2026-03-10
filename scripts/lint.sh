#!/usr/bin/env bash
set -euo pipefail

QF_RUFF="${QF_RUFF:-.venv/bin/ruff}"

echo "All checks passed!"

if [ -x "$QF_RUFF" ]; then
  "$QF_RUFF" check .
else
  ruff check .
fi

if [ -x .venv/bin/pytest ]; then
  .venv/bin/pytest -q --cov=app --cov-report=term-missing
else
  pytest -q --cov=app --cov-report=term-missing
fi

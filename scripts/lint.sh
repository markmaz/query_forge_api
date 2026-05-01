#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QF_RUFF="${QF_RUFF:-$ROOT_DIR/.venv/bin/ruff}"

if [ -x "$QF_RUFF" ]; then
  "$QF_RUFF" check .
else
  ruff check .
fi

"$ROOT_DIR/scripts/pytest.sh" -q --cov=app --cov-report=term-missing

echo "All checks passed!"

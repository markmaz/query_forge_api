#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTEST_BIN="${PYTEST_BIN:-$ROOT_DIR/.venv/bin/pytest}"

if [[ ! -x "$PYTEST_BIN" ]]; then
  PYTEST_BIN="pytest"
fi

echo "==> Lint"
"$ROOT_DIR/scripts/lint.sh"

echo "==> Unit tests (excluding smoke/openapi)"
"$PYTEST_BIN" -q tests -k "not test_routes_smoke and not test_openapi_contract"

echo "==> Route smoke tests"
"$PYTEST_BIN" -q tests/api/test_routes_smoke.py

echo "==> OpenAPI contract tests"
"$PYTEST_BIN" -q tests/openapi/test_openapi_contract.py

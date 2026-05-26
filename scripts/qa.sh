#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTEST_RUNNER="$ROOT_DIR/scripts/pytest.sh"

echo "==> Lint"
"$ROOT_DIR/scripts/lint.sh"

echo "==> Unit tests (excluding smoke/openapi)"
"$PYTEST_RUNNER" -q tests -k "not test_routes_smoke and not test_openapi_contract"

echo "==> Route smoke tests"
"$PYTEST_RUNNER" -q tests/api/test_routes_smoke.py

echo "==> OpenAPI contract tests"
"$PYTEST_RUNNER" -q tests/openapi/test_openapi_contract.py

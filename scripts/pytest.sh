#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_PYTEST_BIN="$ROOT_DIR/.venv/bin/pytest"
PYTEST_BIN="${QF_PYTEST:-${PYTEST_BIN:-$DEFAULT_PYTEST_BIN}}"

if [[ ! -x "$PYTEST_BIN" ]]; then
  echo "error: backend tests must run from the project virtualenv." >&2
  echo "expected pytest at '$DEFAULT_PYTEST_BIN' or set QF_PYTEST/PYTEST_BIN to an executable pytest binary." >&2
  exit 1
fi

exec "$PYTEST_BIN" "$@"

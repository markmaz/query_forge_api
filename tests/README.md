# Tests

## Running

```
pytest -q
```

## Route smoke tests

```
TEST_USERNAME=... TEST_PASSWORD=... pytest -q tests/api/test_routes_smoke.py
```

Notes:
- The Flask app for tests is built via `app.factory.create_app()` in `tests/conftest.py`.
- If `TEST_WORKSPACE_ID` is not set, the tests will try to discover it.
- If discovery fails, set `TEST_WORKSPACE_ID` explicitly.
- You can override the auth endpoint with `TEST_AUTH_URL=/api/v1/auth/auth`.

## OpenAPI contract tests

```
TEST_BASE_URL=http://localhost:5000 \
TEST_USERNAME=... \
TEST_PASSWORD=... \
pytest -q tests/openapi/test_openapi_contract.py
```

Notes:
- Requires a running server exposing `swagger.json` (default: `${TEST_BASE_URL}/swagger.json`).
- You can override the schema URL via `SWAGGER_URL=...`.
- You can override workspace discovery via `TEST_WORKSPACE_ID=...`.
- You can override auth via `TEST_AUTH_URL=...` (absolute or relative).

## All-in-one QA run

```
TEST_BASE_URL=http://localhost:5000 \
TEST_USERNAME=... \
TEST_PASSWORD=... \
TEST_AUTH_URL=/api/v1/auth/auth \
./scripts/qa.sh
```

Notes:
- `scripts/qa.sh` runs lint, unit tests (excluding smoke/openapi), then smoke tests, then openapi tests.
- If `TEST_WORKSPACE_ID` is not set, discovery is attempted; set it if discovery fails.

## Patterns

- Route tests live in `tests/routes/` and `tests/api/` and use Flask's test client.
- Service tests live in `tests/services/` and use fakes from `tests/_support/`.
- External systems are stubbed via fixtures in `tests/conftest.py`.
- Use `ServiceError` assertions for validation and error propagation.

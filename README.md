# QueryForge API

QueryForge API is the Python backend for QueryForge. It serves three related runtime surfaces:

- the primary Flask REST API behind Gunicorn
- Celery workers for async/background jobs
- the standalone QueryForge MCP server for governed AI access

This README is the operational source of truth for backend development, configuration, Docker, and runtime behavior.

## Runtime Components

### Flask API

- entrypoint: `wsgi:app`
- factory: `app/factory.py:create_app`
- default local port: `5000` when running with `python app/main.py`
- default container port: `8000`

### Celery worker

- app: `app.celery_app`
- purpose: async tasks, ingestion, scheduled/background jobs

### QueryForge MCP server

- module: `mcp_server`
- entrypoint: `python -m mcp_server`
- default local/container port: `8001`
- streamable HTTP path: `/mcp`
- auth model: bearer token only
- execution model: preview-only governed query execution, no raw SQL input from clients

## Local Development

### Prerequisites

- Python `3.12`
- MySQL-compatible metadata database
- Qdrant
- Valkey or Redis-compatible broker/cache
- optional: Docker Desktop for container-first local runtime

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements/requirements.txt
```

### Run the Flask API

```bash
python app/main.py
```

### Run the Celery worker

```bash
celery -A app.celery_app worker --loglevel=INFO
```

### Run the MCP server

```bash
python -m mcp_server
```

The MCP server is standalone. It does not run inside the Flask app process.

## Docker

QueryForge is expected to run in Docker.

Use the root-level Compose stack from the workspace root:

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge"
cp .env.docker.example .env
mkdir -p docker
cp docker/customer.env.example docker/customer.env
docker compose up --build
```

Relevant container ports:

- API: `5000 -> 8000`
- MCP: `8001 -> 8001`
- UI: `3000 -> 80`

The backend image in this directory is used for:

- `api`
- `worker`
- `mcp`

The runtime command determines which process starts.

## Configuration

### Traditional backend env

`query-forge-api/.env` is for traditional or direct backend deployments.

Use it for:

- local non-Docker backend runs
- systemd or VM-based deployments
- direct Gunicorn or Celery launches

Do not use it as the source of truth for Docker customer deployments.

### Docker customer env

The Docker stack reads customer-specific runtime settings from:

- `/Users/mmaslak/Local Documents/projects/query_forge/docker/customer.env`

That file is intended for:

- container-safe hostnames
- customer-specific DB credentials
- MCP-specific runtime settings
- container-local service wiring

### Important env groups

#### Core backend runtime

- `JWT_SECRET`
- `DB_HOST`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `DB_PORT`
- `VALKEY_ADDRESS`
- `VALKEY_PORT`
- `QDRANT_URL`
- `QDRANT_API_KEY`

#### Model / AI runtime

- `LLM_INSTANCE_ID`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `SEMANTIC_LLM_ENDPOINT`
- `SEMANTIC_LLM_API_KEY`
- `SEMANTIC_LLM_MODEL`

#### Browser/API integration

- `FRONTEND_BASE_URL`
- `FRONTEND_ALLOWED_ORIGINS`
- `COOKIE_SECURE`
- `COOKIE_SAMESITE`

#### MCP runtime

- `MCP_SERVER_NAME`
- `MCP_SERVER_VERSION`
- `MCP_HOST`
- `MCP_PORT`
- `MCP_STREAMABLE_HTTP_PATH`
- `MCP_ALLOWED_ORIGINS`
- `MCP_INCLUDE_RAW_SQL`
- `MCP_ENABLE_RESOURCES`
- `MCP_ENABLE_SAVED_QUERIES`
- `MCP_PREVIEW_DEFAULT_LIMIT`
- `MCP_PREVIEW_HARD_LIMIT`
- `MCP_PREVIEW_TIMEOUT_SECONDS`
- `MCP_AUDIT_LOGGING`
- `MCP_DEBUG`

### MCP behavior defaults

Operational defaults in the MCP layer are:

- raw SQL excluded from `compile_query` unless `MCP_INCLUDE_RAW_SQL=true`
- preview execution only
- no arbitrary SQL execution
- resources enabled by default
- saved queries enabled by default

## Nginx

Nginx is treated as a first-class runtime layer.

Recommended production host split:

- `api.query-forge.com` → Flask API
- `mcp.query-forge.com` → standalone MCP server

A starter MCP virtual host is provided at:

- `/Users/mmaslak/Local Documents/projects/query_forge/docs/nginx-mcp.query-forge.com.conf.example`

The MCP endpoint should be proxied to:

- `http://127.0.0.1:8001/mcp`

## Tests

### Full backend suite

```bash
pytest -q
```

### Focused MCP suite

```bash
pytest -q mcp_server/tests
```

### Lint

```bash
./scripts/lint.sh
```

### Single test

```bash
pytest tests/path/to/test_file.py::test_name -v
```

## Versioning

- Backend code changes require a patch bump in `version.json`
- `app/api_config.py` route version stays `v1` unless the public API contract changes intentionally

## Related Docs

- MCP implementation spec:
  `/Users/mmaslak/Local Documents/projects/query_forge/docs/plans/queryforge_mcp_codex_implementation_spec.md`
- Docker runtime notes:
  `/Users/mmaslak/Local Documents/projects/query_forge/docs/docker.md`
- MCP package notes:
  `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api/mcp_server/README.md`

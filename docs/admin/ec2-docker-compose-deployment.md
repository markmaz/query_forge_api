# EC2 Docker Compose Deployment

This is the QueryForge equivalent of the Blessing Tree Docker deployment.

```text
Internet
  |
EC2: Docker Compose
  |-- caddy: public HTTP/HTTPS entrypoint with automatic TLS
  |-- frontend: Nginx serving the React build
  |-- api: Flask/Gunicorn on wsgi:app
  |-- mcp: standalone QueryForge MCP server
  |-- celery-worker
  |-- celery-beat
  |-- valkey
  |-- qdrant
  |
RDS MySQL
```

RDS should own the metadata database. The EC2 host should be replaceable: a new host can pull the same images, use the same runtime env file, and run the same Compose stack.

## Files

```text
Dockerfiles:
  query-forge-api/Dockerfile
  query-forge-ui/Dockerfile

Compose:
  docker-compose.yml
  docker-compose.prod.yml

Runtime env template:
  deploy/docker/query-forge.env.example

Caddy config:
  deploy/docker/caddy/Caddyfile

GitHub Actions:
  .github/workflows/deploy-docker-ec2.yml

Remote deployment script:
  scripts/deploy/ec2_docker_deploy.sh
```

## Repository Shape

Blessing Tree is a monorepo. QueryForge is split into:

- `query_forge_api`
- `query_forge_ui`

The deployment workflow lives in the API repo and checks out the UI repo into `query-forge-ui` during the build. By default it uses `markmaz/query_forge_ui` and the same branch name as the API workflow run. Override that with GitHub variables:

| Variable | Default |
| --- | --- |
| `QF_UI_REPOSITORY` | `markmaz/query_forge_ui` |
| `QF_UI_REF` | workflow branch name |

If the UI repo is private and the API repo `GITHUB_TOKEN` cannot read it, add `QF_UI_REPO_TOKEN` as a GitHub secret with read access to the UI repository.

## Container Roles

- `caddy`: public HTTP/HTTPS entrypoint. Terminates TLS and routes API, OAuth, MCP, and frontend traffic.
- `frontend`: internal Nginx container serving static React assets.
- `api`: Gunicorn running `wsgi:app` on port `8000`.
- `mcp`: standalone MCP server on port `8001`.
- `celery-worker`: Celery worker for ingestion, ForgeMatch, Skills, and FlowForge runtime work.
- `celery-beat`: Celery scheduler for Skills and FlowForge due work.
- `valkey`: local Valkey for Celery broker/result backend and runtime cache.
- `qdrant`: local Qdrant vector database.

## Routing

Caddy handles root-level routes that cannot live behind the frontend Nginx `/api` proxy:

```text
/api/*                              -> api:8000
/oauth/*                            -> api:8000
/.well-known/oauth-authorization-server -> api:8000
/mcp*                               -> mcp:8001
/.well-known/oauth-protected-resource -> mcp:8001
everything else                     -> frontend:80
```

## One-Time EC2 Setup

Install Docker and the Compose plugin on the EC2 host.

Create deploy folders:

```bash
sudo mkdir -p /opt/query-forge/shared /opt/query-forge/compose
sudo chown -R "$USER":"$USER" /opt/query-forge
```

Create the runtime env file:

```bash
cp deploy/docker/query-forge.env.example /opt/query-forge/shared/query-forge.env
chmod 600 /opt/query-forge/shared/query-forge.env
```

Edit `/opt/query-forge/shared/query-forge.env` with production values.

Important production values:

- `CURRENT_ENVIRONMENT=production`
- `QF_SITE_ADDRESS=<your-domain>` for HTTPS
- `DB_HOST=<rds endpoint>`
- `FRONTEND_BASE_URL=https://your-domain`
- `INVITE_URL=https://your-domain/auth/register`
- `PASSWORD_RESET_URL=https://your-domain/auth/reset`
- `FLOWFORGE_WEBHOOK_BASE_URL=https://your-domain`
- `COOKIE_SECURE=true`
- `VALKEY_ADDRESS=valkey`
- `QDRANT_URL=http://qdrant:6333`
- `QF_LLM_ENCRYPTION_KEY=<fernet key>` if workspace LLM secrets are configured
- `MCP_RESOURCE_URL=https://your-domain` if MCP is enabled on the same domain
- `MCP_AUTHORIZATION_SERVER_URL=https://your-domain`
- `OAUTH_ISSUER_URL=https://your-domain`

## GitHub Secrets

Required:

| Secret | Purpose |
| --- | --- |
| `EC2_HOST` | EC2 public DNS name or IP |
| `EC2_USER` | SSH user |
| `EC2_SSH_KEY` | Private SSH key for EC2 deploy |

Required if GHCR images are private:

| Secret | Purpose |
| --- | --- |
| `GHCR_USERNAME` | GitHub username or bot account |
| `GHCR_TOKEN` | PAT with `read:packages` for pulling images on EC2 |

Optional:

| Secret or variable | Purpose |
| --- | --- |
| `QF_UI_REPO_TOKEN` | PAT with read access to `query_forge_ui` when `GITHUB_TOKEN` is not enough |
| `VITE_API_URL` | Leave as `/api/v1` for same-origin deployment |

## GitHub Variables

Optional:

| Variable | Default |
| --- | --- |
| `EC2_PORT` | `22` |
| `EC2_DEPLOY_PATH` | `/opt/query-forge` |
| `QF_HTTP_PORT` | `80` |
| `QF_HTTPS_PORT` | `443` |
| `QF_UI_REPOSITORY` | `markmaz/query_forge_ui` |
| `QF_UI_REF` | workflow branch name |
| `QF_RUN_MIGRATIONS` | `false` |

## Deploy

The workflow runs on:

- manual `workflow_dispatch`
- pushes to `main`

It builds and pushes:

```text
ghcr.io/<owner>/query-forge-api:<commit-sha>
ghcr.io/<owner>/query-forge-ui:<commit-sha>
```

Then it uploads the Compose files to EC2 and runs:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile migrate run --rm migrate  # only when QF_RUN_MIGRATIONS=true
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
```

For a first customer cutover, set `QF_RUN_MIGRATIONS=true` only after:

1. the RDS backup/snapshot exists,
2. `/opt/query-forge/shared/query-forge.env` points at the correct database,
3. `QF_MIGRATIONS_MODE=plan` has been run manually and reviewed, and
4. an already-migrated database has been baselined if needed, and
5. the deployment window is open.

After the first successful deploy, leave `QF_RUN_MIGRATIONS=false` unless the
next release contains reviewed database changes.

## Manual Local Build

From `query-forge-api`:

```bash
cp deploy/docker/query-forge.env.example deploy/docker/query-forge.env
docker compose build
docker compose up -d
```

The default local frontend build context is `../query-forge-ui`, matching this workspace layout. Override it with `QF_UI_BUILD_CONTEXT` if needed.

## Migrations

QueryForge currently has raw SQL migration files under:

```text
migrations/
```

The API image includes a one-shot migration runner:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile migrate run --rm migrate
```

The runner:

- applies SQL files in sorted filename order,
- supports `DELIMITER` statements because it uses the MySQL client,
- records applied filenames and SHA-256 checksums in
  `query_forge_schema_migrations`,
- skips already-applied files with matching checksums, and
- fails if an applied migration file checksum changes.

To preview pending migrations:

```bash
QF_MIGRATIONS_MODE=plan docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile migrate run --rm migrate
```

If a production database already has the SQL files applied from an earlier
manual rollout, record those files without re-running them:

```bash
QF_MIGRATIONS_MODE=baseline docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile migrate run --rm migrate
```

Only use `baseline` after comparing the target database to the reviewed
migration set. It marks the current SQL files as already handled.

Use the same reviewed SQL process used for production changes before enabling
`QF_RUN_MIGRATIONS=true` in GitHub Actions.

Workspace-specific setup such as Workflow Intelligence semantic sync is still a
post-migration operational step. It is not run automatically by the Docker
migration service.

## Customer Image Access

The workflow pushes commit-tagged images to GHCR:

```text
ghcr.io/<owner>/query-forge-api:<commit-sha>
ghcr.io/<owner>/query-forge-ui:<commit-sha>
```

If the packages are private, the EC2 host needs `GHCR_USERNAME` and
`GHCR_TOKEN` secrets so `ec2_docker_deploy.sh` can run `docker login`. For a
customer-managed environment, either:

- grant their deployment account read access to the GHCR packages,
- publish a customer-approved release tag to a registry they can pull from, or
- export and transfer the images through their approved artifact process.

Do not rely on `latest` for customer change control; deploy an immutable
commit SHA or release tag.

## TLS

Caddy is the only public web entrypoint.

For local HTTP-only testing:

```text
QF_SITE_ADDRESS=:80
```

For production HTTPS:

```text
QF_SITE_ADDRESS=queryforge.example.com
QF_HTTP_PORT=80
QF_HTTPS_PORT=443
```

DNS must point the domain to the EC2 instance, preferably through an Elastic IP. The EC2 security group must allow inbound `80` and `443`. Port `80` is required because Let's Encrypt uses it for HTTP validation and Caddy redirects HTTP traffic to HTTPS after certificates are issued.

Caddy certificate state is stored in the `caddy-data` Docker volume. Do not delete that volume during normal deployments.

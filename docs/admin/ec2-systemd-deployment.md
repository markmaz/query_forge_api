# EC2 Systemd Deployment

This deployment shape fits the current QueryForge demo servers:

```text
Frontend EC2 t3.small
  |-- Nginx
  |-- React static build
  |-- reverse proxy to backend API/MCP

Backend EC2 t3.xlarge
  |-- Gunicorn / Flask API as a systemd service
  |-- Celery worker as a systemd service
  |-- Celery Beat as a systemd service
  |-- optional MCP server as a systemd service
  |-- Qdrant in Docker
  |-- Valkey/Redis as Docker or system service
  |
RDS MySQL
```

This avoids moving the whole app into Docker. Qdrant can keep running exactly as it does today.

## Files

```text
.github/workflows/deploy-systemd-ec2.yml
scripts/deploy/ec2_systemd_backend_deploy.sh
scripts/deploy/ec2_systemd_frontend_deploy.sh
```

## GitHub Secrets

Use separate backend/frontend secrets when the hosts differ:

| Secret | Purpose |
| --- | --- |
| `BACKEND_EC2_HOST` | Backend EC2 DNS name or IP |
| `BACKEND_EC2_USER` | Backend SSH user |
| `BACKEND_EC2_SSH_KEY` | Backend SSH private key |
| `FRONTEND_EC2_HOST` | Frontend EC2 DNS name or IP |
| `FRONTEND_EC2_USER` | Frontend SSH user |
| `FRONTEND_EC2_SSH_KEY` | Frontend SSH private key |

Fallback names are also supported for one-host/simple setups:

| Secret | Purpose |
| --- | --- |
| `EC2_HOST` | Used when backend/frontend host secrets are absent |
| `EC2_USER` | Used when backend/frontend user secrets are absent |
| `EC2_SSH_KEY` | Used when backend/frontend key secrets are absent |

If the UI repository cannot be read by the default workflow token, add:

| Secret | Purpose |
| --- | --- |
| `QF_UI_REPO_TOKEN` | PAT with read access to `query_forge_ui` |

## GitHub Variables

Important variables:

| Variable | Default |
| --- | --- |
| `BACKEND_DEPLOY_PATH` | `/opt/query-forge/backend` |
| `FRONTEND_DEPLOY_PATH` | `/var/www/query-forge` |
| `QF_API_SERVICE` | `queryforge-api` |
| `QF_CELERY_SERVICE` | `queryforge-celery-worker` |
| `QF_CELERY_BEAT_SERVICE` | `queryforge-celery-beat` |
| `QF_MCP_SERVICE` | empty, meaning do not restart MCP |
| `QF_UI_REPOSITORY` | `markmaz/query_forge_ui` |
| `QF_UI_REF` | workflow branch name |
| `VITE_API_URL` | `/api/v1` |
| `QF_RUN_MIGRATIONS` | `false` |
| `QF_MIGRATION_COMMAND` | empty |

Set the service names to match the actual systemd units on the backend host.

## Backend Host Layout

The deploy script creates:

```text
/opt/query-forge/backend/
  shared/.env
  releases/<release-id>/query-forge-api/
  current -> releases/<release-id>/query-forge-api
```

The backend systemd units should point at:

```text
/opt/query-forge/backend/current
```

The deployment script creates a fresh virtualenv inside each release and installs:

```bash
requirements/requirements.txt
```

## Frontend Host Layout

The frontend deploy script creates:

```text
/var/www/query-forge/
  releases/<release-id>/
  current -> releases/<release-id>
```

Nginx should serve:

```text
/var/www/query-forge/current
```

## Migrations

By default, this workflow does not run database migrations. Apply reviewed SQL migrations before deployment.

To opt into migration execution later, set:

```text
QF_RUN_MIGRATIONS=true
QF_MIGRATION_COMMAND=<your migration command>
```

The command runs from the unpacked backend release directory after dependencies are installed and before systemd restarts.

## Deploy

Run the workflow manually from GitHub Actions:

```text
Deploy Systemd EC2
```

It will:

1. Check out the API repo.
2. Check out the UI repo.
3. Build the React frontend.
4. Validate Python dependencies.
5. Package backend and frontend release archives.
6. Upload backend release to the backend EC2 host.
7. Activate the backend release and restart systemd services.
8. Upload frontend release to the frontend EC2 host.
9. Activate the frontend release and reload Nginx.

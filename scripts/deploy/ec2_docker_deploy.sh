#!/usr/bin/env bash
set -Eeuo pipefail

deploy_dir="${QF_APP_DIR:-/opt/query-forge}"
compose_dir="$deploy_dir/compose"
shared_dir="$deploy_dir/shared"
release_id="${QF_RELEASE_ID:-manual-$(date -u +%Y%m%d%H%M%S)}"
env_file="${QF_ENV_FILE:-$shared_dir/query-forge.env}"

if [ -z "${QF_API_IMAGE:-}" ]; then
  echo "QF_API_IMAGE is required." >&2
  exit 2
fi
if [ -z "${QF_UI_IMAGE:-}" ]; then
  echo "QF_UI_IMAGE is required." >&2
  exit 2
fi

if [ "$(id -u)" -eq 0 ]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
fi

"${sudo_cmd[@]}" mkdir -p "$compose_dir/deploy/docker/caddy" "$shared_dir"
"${sudo_cmd[@]}" chown -R "$(id -u):$(id -g)" "$deploy_dir"

if [ ! -f "$env_file" ]; then
  echo "Runtime env file not found: $env_file" >&2
  echo "Create it from deploy/docker/query-forge.env.example before deploying." >&2
  exit 1
fi

ln -sfn "$env_file" "$compose_dir/deploy/docker/query-forge.env"
ln -sfn "$env_file" "$compose_dir/.env"

if [ -n "${GHCR_USERNAME:-}" ] && [ -n "${GHCR_TOKEN:-}" ]; then
  printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
fi

cd "$compose_dir"

export QF_API_IMAGE
export QF_UI_IMAGE
export QF_ENV_FILE="$env_file"
export QF_IMAGE_TAG="${QF_IMAGE_TAG:-$release_id}"
export QF_HTTP_PORT="${QF_HTTP_PORT:-80}"
export QF_HTTPS_PORT="${QF_HTTPS_PORT:-443}"

docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans

docker image prune -f >/dev/null 2>&1 || true

echo "Deployed QueryForge Docker release: $release_id"

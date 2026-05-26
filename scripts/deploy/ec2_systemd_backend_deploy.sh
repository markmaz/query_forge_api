#!/usr/bin/env bash
set -Eeuo pipefail

release_archive="${1:?release archive is required}"
deploy_dir="${QF_BACKEND_DEPLOY_PATH:-/opt/query-forge/backend}"
release_id="${QF_RELEASE_ID:-manual-$(date -u +%Y%m%d%H%M%S)}"
keep_releases="${QF_KEEP_RELEASES:-5}"
release_dir="$deploy_dir/releases/$release_id"
shared_dir="$deploy_dir/shared"
current_link="$deploy_dir/current"
env_file="${QF_BACKEND_ENV_FILE:-$shared_dir/.env}"

api_service="${QF_API_SERVICE:-queryforge-api}"
celery_service="${QF_CELERY_SERVICE:-queryforge-celery-worker}"
celery_beat_service="${QF_CELERY_BEAT_SERVICE:-queryforge-celery-beat}"
mcp_service="${QF_MCP_SERVICE:-}"
service_user="${QF_SERVICE_USER:-queryforge}"
service_group="${QF_SERVICE_GROUP:-queryforge}"

if [ "$(id -u)" -eq 0 ]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
fi

"${sudo_cmd[@]}" mkdir -p "$deploy_dir/releases" "$shared_dir"
"${sudo_cmd[@]}" chown "$(id -u):$(id -g)" "$deploy_dir" "$deploy_dir/releases"
"${sudo_cmd[@]}" chmod 755 "$shared_dir"

mkdir -p "$release_dir"
tar -xzf "$release_archive" -C "$release_dir"

app_dir="$release_dir/query-forge-api"
if [ ! -d "$app_dir" ]; then
  echo "Release archive did not contain query-forge-api/." >&2
  exit 1
fi

python3.12 -m venv "$app_dir/.venv"
"$app_dir/.venv/bin/python" -m pip install --upgrade pip
"$app_dir/.venv/bin/pip" install -r "$app_dir/requirements/requirements.txt"

if [ -f "$env_file" ]; then
  "${sudo_cmd[@]}" chgrp "$service_group" "$env_file" || true
  "${sudo_cmd[@]}" chmod 640 "$env_file" || true
  ln -sfn "$env_file" "$app_dir/.env"
else
  echo "Warning: backend env file not found at $env_file" >&2
fi

"${sudo_cmd[@]}" mkdir -p "$shared_dir/logs"
"${sudo_cmd[@]}" touch "$shared_dir/log_file" "$shared_dir/default_log"
"${sudo_cmd[@]}" chown -R "$service_user:$service_group" \
  "$shared_dir/logs" "$shared_dir/log_file" "$shared_dir/default_log"
"${sudo_cmd[@]}" chmod 750 "$shared_dir/logs"
"${sudo_cmd[@]}" chmod 664 "$shared_dir/log_file" "$shared_dir/default_log"
ln -sfn "$shared_dir/log_file" "$app_dir/log_file"
ln -sfn "$shared_dir/default_log" "$app_dir/default_log"
rm -rf "$app_dir/logs"
ln -sfn "$shared_dir/logs" "$app_dir/logs"

if [ "${QF_RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ -z "${QF_MIGRATION_COMMAND:-}" ]; then
    echo "QF_RUN_MIGRATIONS=true but QF_MIGRATION_COMMAND is empty." >&2
    exit 2
  fi
  (
    cd "$app_dir"
    eval "$QF_MIGRATION_COMMAND"
  )
fi

ln -sfn "$app_dir" "$current_link"

services=("$api_service" "$celery_service" "$celery_beat_service")
if [ -n "$mcp_service" ]; then
  services+=("$mcp_service")
fi

"${sudo_cmd[@]}" systemctl daemon-reload
for service in "${services[@]}"; do
  if [ -n "$service" ]; then
    "${sudo_cmd[@]}" systemctl restart "$service"
  fi
done

find "$deploy_dir/releases" -mindepth 1 -maxdepth 1 -type d \
  | sort -r \
  | tail -n "+$((keep_releases + 1))" \
  | xargs -r rm -rf

echo "Deployed QueryForge backend systemd release: $release_id"

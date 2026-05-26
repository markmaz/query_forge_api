#!/usr/bin/env bash
set -Eeuo pipefail

release_archive="${1:?frontend release archive is required}"
deploy_dir="${QF_FRONTEND_DEPLOY_PATH:-/var/www/query-forge}"
release_id="${QF_RELEASE_ID:-manual-$(date -u +%Y%m%d%H%M%S)}"
keep_releases="${QF_KEEP_RELEASES:-5}"
release_dir="$deploy_dir/releases/$release_id"
current_link="$deploy_dir/current"

if [ "$(id -u)" -eq 0 ]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
fi

"${sudo_cmd[@]}" mkdir -p "$deploy_dir/releases"
"${sudo_cmd[@]}" chown -R "$(id -u):$(id -g)" "$deploy_dir"

mkdir -p "$release_dir"
tar -xzf "$release_archive" -C "$release_dir"
ln -sfn "$release_dir" "$current_link"
rsync -a --delete \
  --exclude '/.well-known' \
  --exclude '/current' \
  --exclude '/releases' \
  "$release_dir"/ "$deploy_dir"/

if [ "${QF_RESTART_NGINX:-true}" = "true" ]; then
  "${sudo_cmd[@]}" nginx -t
  "${sudo_cmd[@]}" systemctl reload nginx
fi

find "$deploy_dir/releases" -mindepth 1 -maxdepth 1 -type d \
  | sort -r \
  | tail -n "+$((keep_releases + 1))" \
  | xargs -r rm -rf

echo "Deployed QueryForge frontend systemd release: $release_id"

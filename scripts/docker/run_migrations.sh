#!/usr/bin/env bash
set -Eeuo pipefail

migrations_dir="${QF_MIGRATIONS_DIR:-/app/migrations}"
migrations_table="${QF_MIGRATIONS_TABLE:-query_forge_schema_migrations}"
mode="${QF_MIGRATIONS_MODE:-apply}"

if [[ ! "$migrations_table" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "QF_MIGRATIONS_TABLE must contain only letters, numbers, and underscores." >&2
  exit 2
fi

missing=()
for name in DB_HOST DB_USER DB_NAME; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
done
if (( ${#missing[@]} > 0 )); then
  echo "Missing required database environment values: ${missing[*]}" >&2
  exit 2
fi

if [[ ! -d "$migrations_dir" ]]; then
  echo "Migrations directory not found: $migrations_dir" >&2
  exit 2
fi

mysql_args=(
  --protocol=tcp
  --host="$DB_HOST"
  --port="${DB_PORT:-3306}"
  --user="$DB_USER"
  --database="$DB_NAME"
  --batch
  --raw
  --skip-column-names
)

if [[ -n "${DB_PASSWORD:-}" ]]; then
  export MYSQL_PWD="$DB_PASSWORD"
fi
if [[ -n "${DB_SSL_CA:-}" ]]; then
  mysql_args+=(--ssl-ca="$DB_SSL_CA")
fi

mysql_exec() {
  mysql "${mysql_args[@]}" "$@"
}

sql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

checksum_file() {
  sha256sum "$1" | awk '{print $1}'
}

tracking_table_exists() {
  local table_sql
  table_sql="$(sql_escape "$migrations_table")"
  mysql_exec --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = '$table_sql';" \
    | tr -d '\r'
}

ensure_tracking_table() {
  mysql_exec <<SQL
CREATE TABLE IF NOT EXISTS \`$migrations_table\` (
  filename varchar(255) NOT NULL,
  checksum_sha256 char(64) NOT NULL,
  applied_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (filename)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
SQL
}

if [[ "$mode" == "apply" || "$mode" == "baseline" ]]; then
  ensure_tracking_table
fi

tracking_exists="$(tracking_table_exists)"

mapfile -t migration_files < <(find "$migrations_dir" -maxdepth 1 -type f -name '*.sql' | sort)
if (( ${#migration_files[@]} == 0 )); then
  echo "No SQL migrations found in $migrations_dir"
  exit 0
fi

applied_count=0
pending_count=0

for migration_path in "${migration_files[@]}"; do
  filename="$(basename "$migration_path")"
  filename_sql="$(sql_escape "$filename")"
  checksum="$(checksum_file "$migration_path")"
  existing_checksum=""
  if [[ "$tracking_exists" == "1" ]]; then
    existing_checksum="$(
      mysql_exec --execute="SELECT checksum_sha256 FROM \`$migrations_table\` WHERE filename = '$filename_sql' LIMIT 1;" \
        | tr -d '\r'
    )"
  fi

  if [[ -n "$existing_checksum" ]]; then
    if [[ "$existing_checksum" != "$checksum" ]]; then
      echo "Applied migration checksum mismatch for $filename." >&2
      echo "Recorded: $existing_checksum" >&2
      echo "Current:  $checksum" >&2
      exit 1
    fi
    echo "Already applied: $filename"
    continue
  fi

  ((pending_count += 1))
  if [[ "$mode" == "plan" || "$mode" == "dry-run" ]]; then
    echo "Pending: $filename"
    continue
  fi
  if [[ "$mode" == "baseline" ]]; then
    echo "Baselining: $filename"
    checksum_sql="$(sql_escape "$checksum")"
    mysql_exec --execute="INSERT INTO \`$migrations_table\` (filename, checksum_sha256) VALUES ('$filename_sql', '$checksum_sql');"
    ((applied_count += 1))
    continue
  fi
  if [[ "$mode" != "apply" ]]; then
    echo "Unsupported QF_MIGRATIONS_MODE: $mode" >&2
    exit 2
  fi

  echo "Applying: $filename"
  mysql_exec < "$migration_path"
  checksum_sql="$(sql_escape "$checksum")"
  mysql_exec --execute="INSERT INTO \`$migrations_table\` (filename, checksum_sha256) VALUES ('$filename_sql', '$checksum_sql');"
  ((applied_count += 1))
done

if [[ "$mode" == "plan" || "$mode" == "dry-run" ]]; then
  echo "Migration plan complete. Pending migrations: $pending_count"
elif [[ "$mode" == "baseline" ]]; then
  echo "Migration baseline complete. Recorded: $applied_count; pending before run: $pending_count"
else
  echo "Migration apply complete. Applied: $applied_count; pending before run: $pending_count"
fi

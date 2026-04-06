from __future__ import annotations

import json

import click
from flask.cli import with_appcontext

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.services.tenancy.datasource_config_crypto import encrypt_datasource_config
from app.utils.encryption import is_secret_encryption_available


@click.command("encrypt-datasource-secrets")
@with_appcontext
def encrypt_datasource_secrets_command() -> None:
    """Encrypt plaintext datasource passwords/tokens stored in datasource.config_json."""
    if not is_secret_encryption_available():
        raise click.ClickException("QF_ENCRYPTION_KEY is not set or invalid; datasource encryption is unavailable.")

    sql = ForgeMetaSQL()
    rows = sql.execute_query_mappings(
        """
        SELECT id, type, config_json
        FROM datasource
        ORDER BY id
        """
    )

    updated = 0
    scanned = 0
    for row in rows:
        scanned += 1
        config = _coerce_json_obj(row.get("config_json"))
        if not config:
            continue
        datasource_type = str(row.get("type") or "").strip().lower()
        encrypted = encrypt_datasource_config(datasource_type, config)
        if encrypted == config:
            continue
        sql.execute_write(
            "UPDATE datasource SET config_json = :config_json WHERE id = :id",
            {
                "id": int(row["id"]),
                "config_json": json.dumps(encrypted),
            },
        )
        updated += 1

    click.echo(f"Scanned {scanned} datasource row(s); updated {updated}.")


def _coerce_json_obj(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}

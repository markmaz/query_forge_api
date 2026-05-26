from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine.result import Result
from sqlalchemy.pool import QueuePool

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - exercised in production envs without python-dotenv
    load_dotenv = None

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAYLOAD_PATH = REPO_ROOT / "docs/plans/2026-04-14-planner-policy-seed-import.json"

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

if load_dotenv is not None:
    load_dotenv(API_ROOT / ".env")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Idempotently seed planner policy rows from the generated planner-policy seed payload document."
    )
    parser.add_argument(
        "--payload-file",
        default=str(DEFAULT_PAYLOAD_PATH),
        help="Path to the generated planner policy seed payload JSON file.",
    )
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        help="Optional family key to seed. Repeat to limit to specific families.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted or updated without writing to the database.",
    )
    parser.add_argument(
        "--db-host",
        default="",
        help="Override DB host for this run.",
    )
    parser.add_argument(
        "--db-user",
        default="",
        help="Override DB user for this run.",
    )
    parser.add_argument(
        "--db-password",
        default="",
        help="Override DB password for this run.",
    )
    parser.add_argument(
        "--db-name",
        default="",
        help="Override DB name for this run.",
    )
    parser.add_argument(
        "--db-port",
        default="",
        help="Optional DB port override for this run.",
    )
    return parser


def load_seed_document(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Seed payload document must be a JSON object.")
    families = payload.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("Seed payload document must contain a non-empty families list.")
    return payload


def select_families(document: Mapping[str, Any], requested: Sequence[str]) -> List[Dict[str, Any]]:
    families = [dict(item) for item in list(document.get("families") or []) if isinstance(item, dict)]
    if not requested:
        return families

    requested_keys = [str(item or "").strip() for item in requested if str(item or "").strip()]
    family_map = {str(item.get("family_key") or ""): item for item in families}
    missing = [key for key in requested_keys if key not in family_map]
    if missing:
        raise ValueError(f"Unknown family keys: {', '.join(sorted(missing))}")
    return [dict(family_map[key]) for key in requested_keys]


def build_db_params(payload: Mapping[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "policy_key": str(payload.get("policy_key") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "description": payload.get("description"),
        "scope_type": str(payload.get("scope_type") or "").strip(),
        "scope_workspace_id": payload.get("scope_workspace_id"),
        "priority": int(payload.get("priority") or 0),
        "is_active": 1 if bool(payload.get("is_active")) else 0,
        "stop_on_match": 1 if bool(payload.get("stop_on_match")) else 0,
        "policy_json": json.dumps(payload.get("policy_json") or {}, sort_keys=True),
    }
    if "scope_base_domain_id" in payload:
        params["scope_base_domain_id"] = payload.get("scope_base_domain_id")
    return params


def seed_policies(
    *,
    document: Mapping[str, Any],
    requested_families: Sequence[str],
    dry_run: bool,
    db_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    families = select_families(document, requested_families)
    summary: Dict[str, Any] = {
        "payload_file": str(document.get("_payload_file") or ""),
        "dry_run": bool(dry_run),
        "families": [],
        "processed": 0,
        "inserted": 0,
        "updated": 0,
    }

    if dry_run:
        for family in families:
            payloads = [dict(item) for item in list(family.get("payloads") or []) if isinstance(item, dict)]
            summary["families"].append(
                {
                    "family_key": str(family.get("family_key") or ""),
                    "table_name": str(family.get("family_key") or ""),
                    "count": len(payloads),
                    "inserted": 0,
                    "updated": 0,
                    "would_upsert": len(payloads),
                }
            )
            summary["processed"] += len(payloads)
        return summary

    with _transaction(db_config=db_config) as tx:
        for family in families:
            family_key = str(family.get("family_key") or "").strip()
            if family_key == "":
                raise ValueError("Family payload is missing family_key.")
            payloads = [dict(item) for item in list(family.get("payloads") or []) if isinstance(item, dict)]
            family_summary = {
                "family_key": family_key,
                "table_name": family_key,
                "count": len(payloads),
                "inserted": 0,
                "updated": 0,
            }
            for payload in payloads:
                action = _upsert_policy_row(tx=tx, table_name=family_key, payload=payload)
                family_summary[action] += 1
                summary[action] += 1
                summary["processed"] += 1
            summary["families"].append(family_summary)
    return summary


def _build_db_config(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "host": str(getattr(args, "db_host", "") or "").strip(),
        "user": str(getattr(args, "db_user", "") or "").strip(),
        "password": str(getattr(args, "db_password", "") or ""),
        "database": str(getattr(args, "db_name", "") or "").strip(),
        "port": str(getattr(args, "db_port", "") or "").strip(),
    }


def _resolve_db_uri(db_config: Optional[Mapping[str, Any]] = None) -> str:
    direct_uri = str(os.getenv("DB_URI") or "").strip()
    if direct_uri:
        return direct_uri

    db_config = dict(db_config or {})
    host = str(db_config.get("host") or os.getenv("DB_HOST") or "").strip()
    user = str(db_config.get("user") or os.getenv("DB_USER") or "").strip()
    password = str(db_config.get("password") or os.getenv("DB_PASSWORD") or "")
    database = str(db_config.get("database") or os.getenv("DB_NAME") or "").strip()
    port_raw = str(db_config.get("port") or os.getenv("DB_PORT") or "").strip()
    port = int(port_raw) if port_raw else 3306

    missing = [name for name, value in (("DB_HOST", host), ("DB_USER", user), ("DB_NAME", database)) if not value]
    if missing:
        raise RuntimeError(
            "Missing database configuration for planner policy seeding: "
            + ", ".join(missing)
        )

    return str(
        URL.create(
            "mysql+pymysql",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database,
        )
    )


def _build_engine(*, db_config: Optional[Mapping[str, Any]] = None):
    return create_engine(
        _resolve_db_uri(db_config=db_config),
        poolclass=QueuePool,
        pool_size=int(os.getenv("POOL_SIZE", "5")),
        max_overflow=int(os.getenv("MAX_OVERFLOW", "5")),
        pool_timeout=int(os.getenv("POOL_TIMEOUT", "30")),
        pool_recycle=int(os.getenv("POOL_RECYCLE", "1800")),
        pool_pre_ping=True,
    )


class _SeedExecResult:
    def __init__(self, *, rowcount: int, lastrowid: Any) -> None:
        self.rowcount = int(rowcount or 0)
        self.lastrowid = lastrowid


class _SeedTransaction:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        result: Result = self._conn.execute(text(query), params or {})
        return [dict(row) for row in result.mappings().all()]

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        result = self._conn.execute(text(query), params or {})
        return int(result.rowcount or 0)

    def execute_insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> _SeedExecResult:
        result = self._conn.execute(text(query), params or {})
        return _SeedExecResult(rowcount=int(result.rowcount or 0), lastrowid=result.lastrowid)


@contextmanager
def _transaction(*, db_config: Optional[Mapping[str, Any]] = None):
    engine = _build_engine(db_config=db_config)
    conn = engine.connect()
    tx = conn.begin()
    try:
        yield _SeedTransaction(conn)
        tx.commit()
    except SQLAlchemyError:
        tx.rollback()
        raise
    finally:
        conn.close()
        engine.dispose()


def _upsert_policy_row(*, tx: Any, table_name: str, payload: Mapping[str, Any]) -> str:
    params = build_db_params(payload)
    existing_id = _lookup_existing_policy_id(tx=tx, table_name=table_name, params=params)
    if existing_id is not None:
        _update_policy_row(tx=tx, table_name=table_name, params=params, policy_id=existing_id)
        return "updated"
    _insert_policy_row(tx=tx, table_name=table_name, params=params)
    return "inserted"


def _lookup_existing_policy_id(*, tx: Any, table_name: str, params: Mapping[str, Any]) -> Optional[int]:
    where_lines = [
        "policy_key = :policy_key",
        "scope_type = :scope_type",
        "((scope_workspace_id IS NULL AND :scope_workspace_id IS NULL) OR scope_workspace_id = :scope_workspace_id)",
    ]
    if "scope_base_domain_id" in params:
        where_lines.append(
            "((scope_base_domain_id IS NULL AND :scope_base_domain_id IS NULL) OR scope_base_domain_id = :scope_base_domain_id)"
        )
    rows = tx.execute_query_mappings(
        f"""
        SELECT id
        FROM {table_name}
        WHERE {' AND '.join(where_lines)}
        LIMIT 1
        """,
        dict(params),
    )
    if not rows:
        return None
    return int(((rows[0] if rows else {}) or {}).get("id") or 0) or None


def _update_policy_row(*, tx: Any, table_name: str, params: Mapping[str, Any], policy_id: int) -> None:
    set_lines = [
        "policy_key = :policy_key",
        "name = :name",
        "description = :description",
        "scope_type = :scope_type",
        "scope_workspace_id = :scope_workspace_id",
        "priority = :priority",
        "is_active = :is_active",
        "stop_on_match = :stop_on_match",
        "policy_json = :policy_json",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    if "scope_base_domain_id" in params:
        set_lines.insert(4, "scope_base_domain_id = :scope_base_domain_id")
    tx.execute_write(
        f"""
        UPDATE {table_name}
        SET {', '.join(set_lines)}
        WHERE id = :policy_id
        """,
        {**dict(params), "policy_id": int(policy_id)},
    )


def _insert_policy_row(*, tx: Any, table_name: str, params: Mapping[str, Any]) -> None:
    columns = [
        "policy_key",
        "name",
        "description",
        "scope_type",
        "scope_workspace_id",
        "priority",
        "is_active",
        "stop_on_match",
        "policy_json",
    ]
    values = [
        ":policy_key",
        ":name",
        ":description",
        ":scope_type",
        ":scope_workspace_id",
        ":priority",
        ":is_active",
        ":stop_on_match",
        ":policy_json",
    ]
    if "scope_base_domain_id" in params:
        columns.insert(5, "scope_base_domain_id")
        values.insert(5, ":scope_base_domain_id")
    tx.execute_insert(
        f"""
        INSERT INTO {table_name} (
          {', '.join(columns)}
        ) VALUES (
          {', '.join(values)}
        )
        """,
        dict(params),
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _build_parser().parse_args(argv)
    payload_path = Path(args.payload_file).expanduser().resolve()
    document = load_seed_document(payload_path)
    document["_payload_file"] = str(payload_path)
    db_config = _build_db_config(args)
    summary = seed_policies(
        document=document,
        requested_families=args.family,
        dry_run=bool(args.dry_run),
        db_config=db_config,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True, sort_keys=False))


if __name__ == "__main__":
    main()

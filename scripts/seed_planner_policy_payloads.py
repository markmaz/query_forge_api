from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAYLOAD_PATH = REPO_ROOT / "docs/plans/2026-04-14-planner-policy-seed-import.json"

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


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

    from app.adapters.mysql_sql_executor import ForgeMetaSQL

    sql = ForgeMetaSQL()
    with sql.transaction() as tx:
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
    summary = seed_policies(
        document=document,
        requested_families=args.family,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True, sort_keys=False))


if __name__ == "__main__":
    main()

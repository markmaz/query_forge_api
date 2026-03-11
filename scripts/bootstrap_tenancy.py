from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.tenancy.tenancy_bootstrap_service import BootstrapInput, TenancyBootstrapService  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap QueryForge tenancy: organization + datasource + workspace binding (+ optional admin membership)."
    )
    parser.add_argument("--workspace-id", required=True, help="Existing QueryForge workspace id to bind.")
    parser.add_argument("--organization-name", required=True, help="Organization display name.")
    parser.add_argument("--organization-id", default=None, help="Optional explicit organization id.")
    parser.add_argument("--organization-slug", default=None, help="Optional organization slug.")
    parser.add_argument("--organization-description", default=None, help="Optional organization description.")

    parser.add_argument("--datasource-name", required=True, help="Datasource display name.")
    parser.add_argument(
        "--datasource-type",
        required=True,
        choices=["databricks", "snowflake", "mysql", "postgres", "bigquery"],
        help="Datasource type.",
    )
    parser.add_argument("--datasource-slug", default=None, help="Optional datasource slug.")
    parser.add_argument("--datasource-description", default=None, help="Optional datasource description.")
    parser.add_argument("--datasource-secret-ref", default=None, help="Secret reference, e.g. env:DB_PASSWORD.")
    parser.add_argument(
        "--datasource-config-json",
        default=None,
        help="Inline JSON object string for datasource config_json.",
    )
    parser.add_argument(
        "--datasource-config-file",
        default=None,
        help="Path to JSON file for datasource config_json (overrides --datasource-config-json).",
    )

    parser.add_argument("--default-catalog", default=None, help="Optional workspace default catalog.")
    parser.add_argument("--default-schema", default=None, help="Optional workspace default schema.")
    parser.add_argument(
        "--admin-user-id",
        default=None,
        help="Optional user id to grant org_admin (org) and admin (workspace) roles.",
    )
    return parser


def _load_json_config(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.datasource_config_file:
        path = Path(args.datasource_config_file).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("datasource-config-file must contain a JSON object")
        return payload
    if args.datasource_config_json:
        payload = json.loads(args.datasource_config_json)
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("datasource-config-json must be a JSON object")
        return payload
    return None


def main() -> None:
    args = _build_parser().parse_args()
    config_json = _load_json_config(args)

    req = BootstrapInput(
        workspace_id=args.workspace_id,
        organization_name=args.organization_name,
        organization_id=args.organization_id,
        organization_slug=args.organization_slug,
        organization_description=args.organization_description,
        datasource_name=args.datasource_name,
        datasource_type=args.datasource_type,
        datasource_slug=args.datasource_slug,
        datasource_description=args.datasource_description,
        datasource_secret_ref=args.datasource_secret_ref,
        datasource_config_json=config_json,
        default_catalog=args.default_catalog,
        default_schema=args.default_schema,
        admin_user_id=args.admin_user_id,
    )

    result = TenancyBootstrapService().bootstrap(req)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=False))


if __name__ == "__main__":
    main()

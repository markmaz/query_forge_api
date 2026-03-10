from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.exceptions.forge_error import ForgeError  # noqa: E402
from app.services.semantic.plan_service import PlanService  # noqa: E402


def _field_key(field: Dict[str, Any]) -> str:
    table_id = field.get("workspaceTableId")
    column_name = field.get("columnName")
    return f"{table_id}.{column_name}"


def _print_filters(sql_json: Dict[str, Any]) -> None:
    filters = ((sql_json.get("filters") or {}).get("children") or []) if isinstance(sql_json, dict) else []
    print("filters:")
    if not filters:
        print("  - <none>")
        return
    for item in filters:
        if not isinstance(item, dict):
            continue
        field = item.get("field") if isinstance(item.get("field"), dict) else {}
        op = item.get("op")
        value = item.get("value")
        print(f"  - {_field_key(field)} {op} {value!r}")


def _print_columns(sql_json: Dict[str, Any], mapped_columns: List[Dict[str, Any]]) -> None:
    selected = sql_json.get("columns") or []
    print("selected_columns:")
    if not selected:
        print("  - <none>")
    for item in selected:
        if not isinstance(item, dict):
            continue
        field = item.get("field") if isinstance(item.get("field"), dict) else {}
        print(f"  - {_field_key(field)}")

    print("candidate_columns:")
    if not mapped_columns:
        print("  - <none>")
        return
    for row in mapped_columns[:25]:
        if not isinstance(row, dict):
            continue
        print(
            "  - "
            + f"{row.get('table_name')}.{row.get('column_name')} "
            + f"(concept={row.get('concept_key')}, model_column_id={row.get('model_column_id')})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run semantic planner and print grounding details.")
    parser.add_argument("--prompt", required=True, help="Natural-language prompt")
    parser.add_argument("--workspace-id", default=os.getenv("QF_WORKSPACE_ID", "1"), help="Workspace id")
    parser.add_argument("--vertical-norm", default="education", help="Vertical namespace")
    parser.add_argument("--domain-id", type=int, default=None, help="Optional preselected domain id")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM planning stage")
    parser.add_argument("--debug", action="store_true", help="Enable debug payload")
    args = parser.parse_args()

    svc = PlanService()
    payload: Dict[str, Any] = {
        "workspace_id": str(args.workspace_id),
        "vertical_norm": str(args.vertical_norm),
        "prompt": str(args.prompt),
        "debug": bool(args.debug),
    }
    if args.domain_id is not None:
        payload["domain_id"] = int(args.domain_id)

    try:
        out = svc.plan(payload, include_llm=not bool(args.no_llm))
    except ForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if getattr(exc, "details", None):
            print(json.dumps(exc.details, indent=2, ensure_ascii=True), file=sys.stderr)
        return 2

    llm_plan = out.get("llm_plan") if isinstance(out.get("llm_plan"), dict) else {}
    sql_json = llm_plan.get("sql_json") if isinstance(llm_plan.get("sql_json"), dict) else {}
    mapped_columns = list(((out.get("concept_mapping") or {}).get("mapped_columns") or []))

    print(json.dumps({"prompt": out.get("prompt"), "domainId": sql_json.get("domainId")}, ensure_ascii=True))
    _print_filters(sql_json)
    _print_columns(sql_json, mapped_columns)
    warnings = ((out.get("debug") or {}).get("warnings") or [])
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

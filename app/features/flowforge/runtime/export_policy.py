from __future__ import annotations

from typing import Any


class ExportPolicyEvaluator:
    def evaluate(
        self,
        *,
        artifact: dict[str, Any],
        destination: dict[str, Any],
        row_count: int,
    ) -> dict[str, Any]:
        config = destination.get("config_json") or destination.get("config") or {}
        policy = (
            config.get("export_policy")
            if isinstance(config, dict)
            and isinstance(config.get("export_policy"), dict)
            else {}
        )
        classification = self._classification(artifact)
        max_rows = policy.get("max_rows") if isinstance(policy, dict) else None
        if max_rows is not None and row_count > int(max_rows):
            return {
                "allowed": False,
                "reason": "row_count_exceeds_policy",
                "row_count": row_count,
                "max_rows": int(max_rows),
                "classification": classification,
            }
        if bool(policy.get("block_sensitive")) and classification != "unclassified":
            return {
                "allowed": False,
                "reason": "sensitive_export_blocked",
                "row_count": row_count,
                "classification": classification,
            }
        return {
            "allowed": True,
            "reason": "allowed",
            "row_count": row_count,
            "classification": classification,
        }

    def _classification(self, artifact: dict[str, Any]) -> str:
        schema = artifact.get("schema_json") or artifact.get("schema") or {}
        if not isinstance(schema, dict):
            return "unknown"
        sensitivity = schema.get("sensitivity")
        if not isinstance(sensitivity, dict):
            return "unknown"
        return str(sensitivity.get("classification") or "unknown")

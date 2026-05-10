from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
import valkey
from requests import RequestException
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import QDRANT_URL, VALKEY_ADDRESS, VALKEY_CONFIG, VALKEY_PORT, VLLM_BASE_URL, VLLM_MODEL
from app.config.mcp_oauth_config import load_mcp_oauth_config
from app.features.flowforge.runtime.health import get_flowforge_worker_health
from app.ports.sql_executor import ForgeQueryPort
from app.services.tenancy.workspace_llm_service import WorkspaceLLMService

logger = logging.getLogger(__name__)


class AdminHealthService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        vllm_base_url: Optional[str] = None,
        vllm_model: Optional[str] = None,
        qdrant_url: Optional[str] = None,
        mcp_resource_url: Optional[str] = None,
        workspace_llm_service: Optional[WorkspaceLLMService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._vllm_base_url = vllm_base_url or VLLM_BASE_URL
        self._vllm_model = vllm_model or VLLM_MODEL
        self._qdrant_url = qdrant_url or QDRANT_URL
        self._mcp_resource_url = (mcp_resource_url or load_mcp_oauth_config().mcp_resource_url).rstrip("/")
        self._workspace_llm_service = workspace_llm_service or WorkspaceLLMService()

    def check_all(self, *, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        checks: Dict[str, Any] = {}
        checks["app"] = self._check_app()
        checks["mysql"] = self._check_mysql()
        checks["llms"] = self._check_workspace_llms(workspace_id=workspace_id)
        checks["qdrant"] = self._check_qdrant()
        checks["mcp"] = self._check_mcp()
        checks["broker"] = self.check_broker()
        checks["flowforge"] = self._check_flowforge()

        statuses = [c["status"] for c in checks.values()]
        if all(s == "ok" for s in statuses):
            overall = "healthy"
        elif any(s == "ok" for s in statuses):
            overall = "degraded"
        else:
            overall = "unhealthy"

        return {"overall": overall, "checks": checks}

    def _check_app(self) -> Dict[str, Any]:
        return {"status": "ok"}

    def _check_mysql(self) -> Dict[str, Any]:
        start = time.perf_counter()
        try:
            rows = self._sql.execute_query("SELECT 1")
            latency_ms = int((time.perf_counter() - start) * 1000)
            if rows and rows[0][0] == 1:
                return {"status": "ok", "latency_ms": latency_ms}
            return {"status": "error", "latency_ms": latency_ms, "error": "unexpected result"}
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("MySQL health check failed")
            return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}

    def _check_vllm(self) -> Dict[str, Any]:
        url = f"{self._vllm_base_url}/v1/models"
        start = time.perf_counter()
        try:
            resp = requests.get(url, timeout=10)
            latency_ms = int((time.perf_counter() - start) * 1000)
            resp.raise_for_status()
            return {
                "status": "ok",
                "latency_ms": latency_ms,
                "model": self._vllm_model,
                "upstream": resp.json(),
            }
        except (RequestException, OSError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("vLLM health check failed")
            return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}

    def _check_workspace_llms(self, *, workspace_id: Optional[str]) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip()
        if not ws:
            return {
                "status": "degraded",
                "workspace_id": None,
                "total_count": 0,
                "active_count": 0,
                "healthy_count": 0,
                "failed_count": 0,
                "active_failed_count": 0,
                "latency_ms": None,
                "llms": [],
                "issues": ["Workspace LLM health requires X-Workspace-Id."],
            }

        try:
            configs = self._workspace_llm_service.get_all_for_workspace(ws)
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            logger.exception("Workspace LLM health list failed")
            return {
                "status": "error",
                "workspace_id": ws,
                "total_count": None,
                "active_count": None,
                "healthy_count": None,
                "failed_count": None,
                "active_failed_count": None,
                "latency_ms": None,
                "llms": [],
                "error": str(exc),
                "issues": ["Workspace LLM configurations could not be loaded."],
            }

        checks: list[dict[str, Any]] = []
        total_latency_ms = 0
        for cfg in configs:
            llm_id = _to_int_or_none(cfg.get("id"))
            start = time.perf_counter()
            if llm_id is None:
                result = {"success": False, "message": "LLM configuration is missing an id."}
            else:
                try:
                    result = self._workspace_llm_service.test_connection(llm_id)
                except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
                    logger.exception("Workspace LLM health check failed llm_id=%s", llm_id)
                    result = {"success": False, "message": str(exc)}
            latency_ms = int((time.perf_counter() - start) * 1000)
            total_latency_ms += latency_ms
            ok = bool(result.get("success"))
            checks.append(
                {
                    "id": llm_id,
                    "name": str(cfg.get("name") or "").strip() or f"LLM {llm_id or '-'}",
                    "provider": str(cfg.get("provider") or "").strip(),
                    "model": str(cfg.get("model_name") or "").strip(),
                    "role": str(cfg.get("role") or "").strip(),
                    "endpoint": _display_llm_endpoint(cfg),
                    "active": bool(cfg.get("is_active")),
                    "status": "ok" if ok else "error",
                    "latency_ms": latency_ms,
                    "message": str(result.get("message") or "").strip(),
                }
            )

        total_count = len(checks)
        active_count = sum(1 for item in checks if item["active"])
        healthy_count = sum(1 for item in checks if item["status"] == "ok")
        failed_count = total_count - healthy_count
        active_failed_count = sum(1 for item in checks if item["active"] and item["status"] != "ok")

        issues: list[str] = []
        if total_count == 0:
            issues.append("No workspace LLM configurations are defined.")
        if active_count == 0 and total_count > 0:
            issues.append("No active workspace LLM configurations are enabled.")
        if failed_count > 0:
            issues.append(f"{failed_count} workspace LLM configuration(s) failed health checks.")

        if total_count == 0 or active_count == 0 or failed_count > 0:
            status = "degraded"
        else:
            status = "ok"

        return {
            "status": status,
            "workspace_id": ws,
            "total_count": total_count,
            "active_count": active_count,
            "healthy_count": healthy_count,
            "failed_count": failed_count,
            "active_failed_count": active_failed_count,
            "latency_ms": int(total_latency_ms / total_count) if total_count else None,
            "llms": checks,
            "issues": issues,
        }

    def _check_qdrant(self) -> Dict[str, Any]:
        url = f"{self._qdrant_url}/healthz"
        start = time.perf_counter()
        try:
            resp = requests.get(url, timeout=10)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if resp.status_code == 200:
                return {"status": "ok", "latency_ms": latency_ms}
            return {"status": "error", "latency_ms": latency_ms, "error": f"HTTP {resp.status_code}"}
        except (RequestException, OSError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Qdrant health check failed")
            return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}

    def _check_mcp(self) -> Dict[str, Any]:
        url = f"{self._mcp_resource_url}/healthz"
        start = time.perf_counter()
        try:
            resp = requests.get(url, timeout=5)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if resp.status_code == 200:
                payload = _safe_json(resp)
                return {
                    "status": "ok",
                    "latency_ms": latency_ms,
                    "url": self._mcp_resource_url,
                    "version": str(payload.get("version") or ""),
                }
            return {
                "status": "error",
                "latency_ms": latency_ms,
                "url": self._mcp_resource_url,
                "error": f"HTTP {resp.status_code}",
            }
        except (RequestException, OSError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("MCP health check failed")
            return {"status": "error", "latency_ms": latency_ms, "url": self._mcp_resource_url, "error": str(exc)}

    def check_broker(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "broker_url": _mask_broker_url(VALKEY_CONFIG),
            "valkey": {
                "address": VALKEY_ADDRESS,
                "port": int(VALKEY_PORT or 0),
                "ping_ok": False,
                "ping_response": None,
                "error": None,
            },
            "celery": {
                "broker_connect_ok": False,
                "broker_error": None,
                "worker_ping_ok": False,
                "workers": [],
                "worker_error": None,
            },
        }

        try:
            client = valkey.Valkey(
                host=str(VALKEY_ADDRESS or "localhost"),
                port=int(VALKEY_PORT or 6379),
                db=0,
                socket_timeout=1.5,
            )
            pong = client.ping()
            out["valkey"]["ping_ok"] = bool(pong)
            out["valkey"]["ping_response"] = str(pong)
        except (valkey.ValkeyError, OSError, ValueError) as exc:
            out["valkey"]["error"] = str(exc)

        try:
            with celery.connection_for_write() as conn:
                conn.ensure_connection(max_retries=0)
            out["celery"]["broker_connect_ok"] = True
        except (OSError, RuntimeError, ValueError) as exc:
            out["celery"]["broker_error"] = str(exc)

        try:
            inspector = celery.control.inspect(timeout=1.5)
            ping_map = inspector.ping() or {}
            workers = sorted(str(name) for name in ping_map.keys())
            out["celery"]["worker_ping_ok"] = bool(workers)
            out["celery"]["workers"] = workers
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            out["celery"]["worker_error"] = str(exc)

        core_ok = bool(out["valkey"]["ping_ok"] and out["celery"]["broker_connect_ok"])
        workers_ok = bool(out["celery"]["worker_ping_ok"])
        out["ok"] = bool(core_ok and workers_ok)
        if out["ok"]:
            out["status"] = "ok"
        elif core_ok:
            out["status"] = "degraded"
        else:
            out["status"] = "error"
        return out

    def _check_flowforge(self) -> Dict[str, Any]:
        heartbeat = get_flowforge_worker_health()
        try:
            metrics = self._query_flowforge_operational_metrics()
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            logger.exception("FlowForge health metrics failed")
            return {
                "status": "error",
                "worker": heartbeat,
                "error": str(exc),
                "metrics": {
                    "pending_notification_count": None,
                    "failed_notification_count": None,
                    "stuck_run_count": None,
                    "failed_run_count": None,
                    "schedule_backlog_count": None,
                    "failed_import_count": None,
                    "failed_export_count": None,
                    "stuck_approval_count": None,
                    "invalid_production_run_as_count": None,
                    "expired_artifact_count": None,
                    "artifact_retention_pending_count": None,
                },
            }

        issues: list[str] = []
        if not heartbeat.get("healthy"):
            issues.append(str(heartbeat.get("reason") or "FlowForge worker heartbeat is unhealthy."))
        if int(metrics.get("stuck_run_count") or 0) > 0:
            issues.append(f"{metrics['stuck_run_count']} workflow run(s) appear stuck.")
        if int(metrics.get("failed_run_count") or 0) > 0:
            issues.append(f"{metrics['failed_run_count']} workflow run(s) failed in the last 24 hours.")
        if int(metrics.get("failed_notification_count") or 0) > 0:
            issues.append(f"{metrics['failed_notification_count']} FlowForge notification side effect(s) failed.")
        if int(metrics.get("schedule_backlog_count") or 0) > 0:
            issues.append(f"{metrics['schedule_backlog_count']} scheduled FlowForge trigger(s) are backlogged.")
        if int(metrics.get("failed_import_count") or 0) > 0:
            issues.append(f"{metrics['failed_import_count']} data import(s) failed in the last 24 hours.")
        if int(metrics.get("failed_export_count") or 0) > 0:
            issues.append(f"{metrics['failed_export_count']} data export(s) failed in the last 24 hours.")
        if int(metrics.get("stuck_approval_count") or 0) > 0:
            issues.append(f"{metrics['stuck_approval_count']} approval task(s) are overdue or stalled.")
        if int(metrics.get("invalid_production_run_as_count") or 0) > 0:
            issues.append(
                f"{metrics['invalid_production_run_as_count']} production workflow(s) have invalid run-as governance."
            )
        if int(metrics.get("artifact_retention_pending_count") or 0) > 0:
            issues.append(f"{metrics['artifact_retention_pending_count']} dataset artifact(s) are past retention.")
        unavailable_metrics = [
            key
            for key in (
                "schedule_backlog_count",
                "failed_import_count",
                "failed_export_count",
                "stuck_approval_count",
                "invalid_production_run_as_count",
                "expired_artifact_count",
                "artifact_retention_pending_count",
            )
            if metrics.get(key) is None
        ]
        if unavailable_metrics:
            issues.append("Some FlowForge operations metrics are unavailable; apply the latest FlowForge migrations.")

        return {
            "status": "ok" if not issues else "degraded",
            "worker": heartbeat,
            "metrics": metrics,
            "issues": issues,
        }

    def _query_flowforge_operational_metrics(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        params = {
            "stuck_cutoff": now - timedelta(minutes=30),
            "failure_cutoff": now - timedelta(hours=24),
            "schedule_backlog_cutoff": now - timedelta(minutes=5),
            "approval_due_cutoff": now,
            "approval_stale_cutoff": now - timedelta(hours=24),
        }
        return {
            "pending_notification_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_notifications
                WHERE status = 'pending'
                """,
                {},
                metric_name="pending_notification_count",
            ),
            "failed_notification_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_notifications
                WHERE status = 'failed'
                """,
                {},
                metric_name="failed_notification_count",
            ),
            "stuck_run_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_runs
                WHERE status IN ('queued', 'waiting', 'running')
                  AND updated_at <= :stuck_cutoff
                """,
                params,
                metric_name="stuck_run_count",
            ),
            "failed_run_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_runs
                WHERE status = 'failed'
                  AND COALESCE(failed_at, updated_at, started_at) >= :failure_cutoff
                """,
                params,
                metric_name="failed_run_count",
            ),
            "schedule_backlog_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_schedule_runs
                WHERE status IN ('pending', 'started')
                  AND scheduled_for <= :schedule_backlog_cutoff
                """,
                params,
                metric_name="schedule_backlog_count",
            ),
            "failed_import_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_data_movement_audit
                WHERE action_type = 'import'
                  AND status = 'failed'
                  AND COALESCE(completed_at, started_at, created_at) >= :failure_cutoff
                """,
                params,
                metric_name="failed_import_count",
            ),
            "failed_export_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_data_movement_audit
                WHERE action_type = 'export'
                  AND status = 'failed'
                  AND COALESCE(completed_at, started_at, created_at) >= :failure_cutoff
                """,
                params,
                metric_name="failed_export_count",
            ),
            "stuck_approval_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_human_tasks
                WHERE task_type = 'approval'
                  AND status IN ('pending', 'waiting')
                  AND (
                    (due_at IS NOT NULL AND due_at <= :approval_due_cutoff)
                    OR (due_at IS NULL AND created_at <= :approval_stale_cutoff)
                  )
                """,
                params,
                metric_name="stuck_approval_count",
            ),
            "invalid_production_run_as_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_workflow_definitions d
                LEFT JOIN flowforge_workspace_settings s
                  ON s.workspace_id = d.workspace_id
                LEFT JOIN flowforge_workflow_versions pv
                  ON pv.workspace_id = d.workspace_id
                 AND pv.workflow_definition_id = d.id
                 AND pv.id = d.latest_published_version_id
                 AND pv.version_status = 'published'
                 AND pv.archived_at IS NULL
                WHERE d.archived_at IS NULL
                  AND d.lifecycle = 'production'
                  AND (
                    d.run_as_principal_type IS NULL
                    OR d.run_as_principal_id IS NULL
                    OR d.run_as_principal_id = ''
                    OR d.run_as_principal_type NOT IN ('user', 'service_principal', 'workspace_principal')
                    OR (
                      d.run_as_principal_type = 'user'
                      AND COALESCE(
                        JSON_UNQUOTE(JSON_EXTRACT(s.settings_json, '$.allow_user_run_as_for_production')),
                        'false'
                      ) NOT IN ('true', '1', 'yes', 'on')
                    )
                    OR (
                      d.run_as_principal_type = 'user'
                      AND COALESCE(
                        JSON_UNQUOTE(JSON_EXTRACT(s.settings_json, '$.require_service_principal_for_automated_triggers')),
                        'true'
                      ) IN ('true', '1', 'yes', 'on')
                      AND (
                        pv.graph_json LIKE '%schedule_trigger%'
                        OR pv.graph_json LIKE '%webhook_trigger%'
                        OR pv.graph_json LIKE '%file_watch_trigger%'
                      )
                    )
                    OR (
                      d.run_as_principal_type = 'workspace_principal'
                      AND d.run_as_principal_id <> d.workspace_id
                    )
                    OR (
                      d.run_as_principal_type = 'service_principal'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM mcp_app_clients c
                        JOIN mcp_principal_grants g
                          ON g.principal_type = 'app'
                         AND g.principal_id = c.client_id
                         AND g.workspace_id = d.workspace_id
                        WHERE c.client_id = d.run_as_principal_id
                          AND c.owning_workspace_id = d.workspace_id
                          AND c.revoked_at IS NULL
                          AND (c.expires_at IS NULL OR c.expires_at > CURRENT_TIMESTAMP)
                          AND g.enabled = 1
                          AND g.revoked_at IS NULL
                          AND (g.expires_at IS NULL OR g.expires_at > CURRENT_TIMESTAMP)
                      )
                    )
                  )
                """,
                {},
                metric_name="invalid_production_run_as_count",
            ),
            "expired_artifact_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_dataset_artifacts
                WHERE status = 'expired'
                """,
                {},
                metric_name="expired_artifact_count",
            ),
            "artifact_retention_pending_count": self._query_optional_flowforge_count(
                """
                SELECT COUNT(*) AS metric_count
                FROM flowforge_dataset_artifacts
                WHERE expires_at IS NOT NULL
                  AND expires_at <= CURRENT_TIMESTAMP
                  AND status NOT IN ('expired', 'deleted')
                """,
                {},
                metric_name="artifact_retention_pending_count",
            ),
            "stuck_run_threshold_minutes": 30,
            "failed_run_window_hours": 24,
            "schedule_backlog_threshold_minutes": 5,
            "approval_stale_threshold_hours": 24,
        }

    def _query_optional_flowforge_count(
        self,
        query: str,
        params: dict[str, Any],
        *,
        metric_name: str,
    ) -> int | None:
        try:
            rows = self._sql.execute_query_mappings(query, params)
        except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
            logger.warning("FlowForge health metric unavailable: %s (%s)", metric_name, exc)
            return None
        row = dict(rows[0]) if rows else {}
        value = row.get("metric_count")
        return int(value) if value is not None else 0


def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _display_llm_endpoint(cfg: dict[str, Any]) -> str:
    provider = str(cfg.get("provider") or "").strip().lower()
    endpoint = str(cfg.get("endpoint_url") or "").strip()
    if endpoint:
        return endpoint
    if provider == "openai":
        return "https://api.openai.com/v1"
    if provider == "anthropic":
        return "https://api.anthropic.com/v1"
    return ""


def _to_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _mask_broker_url(raw_url: str) -> str:
    text = str(raw_url or "").strip()
    if text == "":
        return ""
    try:
        parts = urlsplit(text)
        netloc = parts.netloc or ""
        if "@" not in netloc:
            return text
        creds, host_part = netloc.split("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            masked_creds = f"{user}:***"
        else:
            masked_creds = "***"
        return urlunsplit((parts.scheme, f"{masked_creds}@{host_part}", parts.path, parts.query, parts.fragment))
    except ValueError:
        return text

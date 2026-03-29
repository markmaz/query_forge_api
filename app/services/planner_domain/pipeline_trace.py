"""Pipeline trace and profile logging utilities for the planner domain."""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from logging.handlers import WatchedFileHandler
from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.config import (
    PLANNER_UNIFIED_LLM,
    QF_PLAN_DOMAIN_FAST_MODE_DEFAULT,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_CHARS,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_ITEMS,
    QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED,
    QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE,
)
from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)

_PROFILE_LOGGER_NAME = "planner_domain.pipeline_profile"
_PROFILE_LOGGER_INITIALIZED = False
_TRACE_LOGGER_NAME = "planner_domain.pipeline_trace"
_TRACE_LOGGER_INITIALIZED = False

_PIPELINE_PROFILE_HEADER_RE = re.compile(
    r"plan_domain_pipeline\s+trace_id=(?P<trace_id>\S+)\s+workspace_id=(?P<workspace_id>\S+)\s+"
    r"user_id=(?P<user_id>\S+)\s+conversation_id=(?P<conversation_id>\S+)\s+total_ms=(?P<total_ms>\d+)"
)
_PIPELINE_PROFILE_STEP_RE = re.compile(r"^\s*(?P<index>\d+)\.\s+(?P<label>.+):\s+(?P<ms>\d+)ms\s*$")
_PIPELINE_PROFILE_TIMESTAMP_RE = re.compile(r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+[0-9:,]+)")


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


def _project_root_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _resolve_plan_domain_log_path(configured_path: str, default_path: str) -> str:
    token = str(configured_path or "").strip() or str(default_path or "").strip()
    if token == "":
        token = "logs/plan_domain_pipeline.log"
    if os.path.isabs(token):
        return token
    return os.path.abspath(os.path.join(_project_root_dir(), token))


def _pipeline_profile_logger() -> logging.Logger:
    global _PROFILE_LOGGER_INITIALIZED

    profile_logger = logging.getLogger(_PROFILE_LOGGER_NAME)
    if _PROFILE_LOGGER_INITIALIZED:
        return profile_logger

    profile_logger.setLevel(logging.INFO)
    profile_logger.propagate = False
    try:
        log_path = _resolve_plan_domain_log_path(
            str(QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE or ""),
            "logs/plan_domain_pipeline_timing.log",
        )
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handler = WatchedFileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
        profile_logger.addHandler(handler)
        _PROFILE_LOGGER_INITIALIZED = True
    except Exception as exc:
        logger.warning("planner_domain timing profile logger init failed err=%s", exc)
    return profile_logger


def _pipeline_trace_logger() -> logging.Logger:
    global _TRACE_LOGGER_INITIALIZED

    trace_logger = logging.getLogger(_TRACE_LOGGER_NAME)
    if _TRACE_LOGGER_INITIALIZED:
        return trace_logger

    trace_logger.setLevel(logging.INFO)
    trace_logger.propagate = False
    try:
        log_path = _resolve_plan_domain_log_path(
            str(QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE or ""),
            "logs/plan_domain_pipeline_trace.jsonl",
        )
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handler = WatchedFileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        trace_logger.addHandler(handler)
        _TRACE_LOGGER_INITIALIZED = True
    except Exception as exc:
        logger.warning("planner_domain pipeline trace logger init failed err=%s", exc)
    return trace_logger


def _sanitize_pipeline_trace_value(value: Any, *, depth: int = 0) -> Any:
    max_chars = max(200, int(QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_CHARS or 12000))
    max_items = max(10, int(QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_ITEMS or 100))
    if depth >= 8:
        return "<max_depth>"
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        token = value.strip()
        return token[:max_chars]
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= max_items:
                out["__truncated__"] = f"{len(value) - max_items} more"
                break
            out[str(k)] = _sanitize_pipeline_trace_value(v, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes, bytearray)):
        items: List[Any] = []
        for idx, item in enumerate(value):
            if idx >= max_items:
                items.append(f"<truncated:{len(value) - max_items} more>")
                break
            items.append(_sanitize_pipeline_trace_value(item, depth=depth + 1))
        return items
    return str(value)[:max_chars]


def _append_pipeline_trace_step(
    *,
    trace: Any,
    enabled: bool,
    step: str,
    data: Mapping[str, Any],
) -> None:
    if not enabled:
        return
    if not isinstance(trace, dict):
        return
    steps = trace.setdefault("steps", [])
    if not isinstance(steps, list):
        trace["steps"] = []
        steps = trace["steps"]
    steps.append(
        {
            "step": str(step or "").strip(),
            "data": _sanitize_pipeline_trace_value(data),
        }
    )


def _add_pipeline_step(
    *,
    profile_steps: List[Dict[str, Any]],
    enabled: bool,
    step: str,
    label: str,
    started_at: float,
) -> int:
    elapsed = _elapsed_ms(started_at)
    if enabled:
        profile_steps.append(
            {
                "step": step,
                "label": label,
                "ms": elapsed,
            }
        )
    return elapsed


def _emit_pipeline_profile_log(
    *,
    enabled: bool,
    trace_id: str,
    workspace_id: str,
    user_id: str,
    conversation_id: str,
    prompt: str,
    total_ms: int,
    steps: Sequence[Mapping[str, Any]],
) -> None:
    if not enabled:
        return
    try:
        lines = [
            (
                f"plan_domain_pipeline trace_id={trace_id} workspace_id={workspace_id} user_id={user_id} "
                f"conversation_id={conversation_id} total_ms={total_ms}"
            ),
            f"prompt={prompt[:240]}",
        ]
        for idx, row in enumerate(steps, start=1):
            label = str(row.get("label") or row.get("step") or "").strip()
            ms = int(row.get("ms") or 0)
            lines.append(f"{idx}. {label}: {ms}ms")
        _pipeline_profile_logger().info("\n".join(lines))
    except Exception as exc:
        logger.warning("planner_domain timing profile emit failed trace_id=%s err=%s", trace_id, exc)


def _emit_pipeline_trace_log(
    *,
    enabled: bool,
    trace_payload: Mapping[str, Any],
) -> None:
    if not enabled:
        return
    try:
        payload = _sanitize_pipeline_trace_value(trace_payload)
        _pipeline_trace_logger().info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    except Exception as exc:
        logger.warning(
            "planner_domain pipeline trace emit failed trace_id=%s err=%s",
            trace_payload.get("trace_id"),
            exc,
        )


def _parse_pipeline_profile_record(*, header_line: str, detail_lines: Sequence[str]) -> Optional[Dict[str, Any]]:
    header_match = _PIPELINE_PROFILE_HEADER_RE.search(str(header_line or ""))
    if header_match is None:
        return None

    total_ms = _to_int(header_match.group("total_ms")) or 0
    timestamp_match = _PIPELINE_PROFILE_TIMESTAMP_RE.search(str(header_line or ""))
    timestamp = str((timestamp_match.group("timestamp") if timestamp_match else "") or "").strip()

    prompt = ""
    steps: List[Dict[str, Any]] = []
    for raw in detail_lines:
        text = str(raw or "").strip()
        if text == "":
            continue
        if text.startswith("prompt="):
            prompt = text.removeprefix("prompt=").strip()
            continue
        step_match = _PIPELINE_PROFILE_STEP_RE.match(text)
        if step_match is None:
            continue
        steps.append(
            {
                "index": _to_int(step_match.group("index")) or 0,
                "label": str(step_match.group("label") or "").strip(),
                "ms": _to_int(step_match.group("ms")) or 0,
            }
        )

    return {
        "trace_id": str(header_match.group("trace_id") or "").strip(),
        "workspace_id": str(header_match.group("workspace_id") or "").strip(),
        "user_id": str(header_match.group("user_id") or "").strip(),
        "conversation_id": str(header_match.group("conversation_id") or "").strip(),
        "total_ms": total_ms,
        "timestamp": timestamp,
        "prompt": prompt,
        "steps": steps,
    }


def _read_pipeline_profile_from_log(
    *,
    trace_id: str,
    workspace_id: str = "",
    user_id: str = "",
) -> Optional[Dict[str, Any]]:
    log_path = _resolve_plan_domain_log_path(
        str(QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE or ""),
        "logs/plan_domain_pipeline_timing.log",
    )
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception as exc:
        raise ForgeError(
            "Failed to read pipeline profile log",
            status_code=500,
            details={"trace_id": trace_id, "log_file": log_path, "error": str(exc)},
        ) from exc

    records: List[Tuple[str, List[str]]] = []
    current_header: Optional[str] = None
    current_lines: List[str] = []
    for line in lines:
        if "plan_domain_pipeline trace_id=" in line:
            if current_header is not None:
                records.append((current_header, list(current_lines)))
            current_header = line
            current_lines = []
            continue
        if current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        records.append((current_header, list(current_lines)))

    for header_line, detail_lines in reversed(records):
        parsed = _parse_pipeline_profile_record(header_line=header_line, detail_lines=detail_lines)
        if not parsed:
            continue
        if str(parsed.get("trace_id") or "") != trace_id:
            continue
        if workspace_id and str(parsed.get("workspace_id") or "") != workspace_id:
            continue
        if user_id and str(parsed.get("user_id") or "") != user_id:
            continue
        parsed["log_file"] = log_path
        parsed["profiling_enabled"] = bool(QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED)
        return parsed

    return None


def _read_pipeline_trace_from_log(
    *,
    trace_id: str,
    workspace_id: str = "",
    user_id: str = "",
) -> Optional[Dict[str, Any]]:
    log_path = _resolve_plan_domain_log_path(
        str(QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE or ""),
        "logs/plan_domain_pipeline_trace.jsonl",
    )
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception:
        logger.exception("Failed to read pipeline trace log")
        return None

    for line in reversed(lines):
        text = str(line or "").strip()
        if text == "":
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        if str(parsed.get("trace_id") or "").strip() != trace_id:
            continue
        if workspace_id and str(parsed.get("workspace_id") or "").strip() != workspace_id:
            continue
        if user_id and str(parsed.get("user_id") or "").strip() != user_id:
            continue
        parsed["log_file"] = log_path
        parsed["trace_enabled"] = bool(QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED)
        return parsed
    return None


def _list_pipeline_profiles_from_log(*, limit: int = 50) -> List[Dict[str, Any]]:
    log_path = _resolve_plan_domain_log_path(
        str(QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE or ""),
        "logs/plan_domain_pipeline_timing.log",
    )
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception:
        logger.exception("Failed to read pipeline profile log for listing")
        return []

    records: List[Tuple[str, List[str]]] = []
    current_header: Optional[str] = None
    current_lines: List[str] = []
    for line in lines:
        if "plan_domain_pipeline trace_id=" in line:
            if current_header is not None:
                records.append((current_header, list(current_lines)))
            current_header = line
            current_lines = []
            continue
        if current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        records.append((current_header, list(current_lines)))

    profiles: List[Dict[str, Any]] = []
    for header_line, detail_lines in reversed(records):
        parsed = _parse_pipeline_profile_record(header_line=header_line, detail_lines=detail_lines)
        if parsed:
            profiles.append(parsed)
        if len(profiles) >= limit:
            break
    return profiles


def _capabilities_summary(capabilities: Mapping[str, Any]) -> Dict[str, Any]:
    dims = list(capabilities.get("dimensions") or [])
    filters = list(capabilities.get("filter_columns") or [])
    times = list(capabilities.get("time_columns") or [])
    domain_metrics = list(capabilities.get("domain_metrics") or [])
    user_metrics = list(capabilities.get("user_metrics") or [])
    overlay_metrics = list(capabilities.get("overlay_metrics") or [])
    return {
        "domain_id": _to_int(capabilities.get("domain_id")),
        "domain_version": _to_int(capabilities.get("domain_version")),
        "dimension_count": len(dims),
        "filter_count": len(filters),
        "time_count": len(times),
        "domain_metric_count": len(domain_metrics),
        "user_metric_count": len(user_metrics),
        "overlay_metric_count": len(overlay_metrics),
    }


class PipelineTraceService:
    """Small facade over pipeline trace/profile persistence helpers."""

    def get_pipeline_profile(
        self,
        *,
        trace_id: str,
        workspace_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        profile = _read_pipeline_profile_from_log(
            trace_id=trace_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if profile is None:
            return None
        pipeline_trace = _read_pipeline_trace_from_log(
            trace_id=trace_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if pipeline_trace is not None:
            profile["pipeline_trace"] = pipeline_trace
        return profile

    def list_pipeline_profiles(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        return _list_pipeline_profiles_from_log(limit=limit)

    def emit_profile_log(
        self,
        *,
        enabled: bool,
        trace_id: str,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        prompt: str,
        total_ms: int,
        steps: Sequence[Mapping[str, Any]],
    ) -> None:
        _emit_pipeline_profile_log(
            enabled=enabled,
            trace_id=trace_id,
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            prompt=prompt,
            total_ms=total_ms,
            steps=steps,
        )

    def emit_trace_log(self, *, enabled: bool, trace_payload: Mapping[str, Any]) -> None:
        _emit_pipeline_trace_log(enabled=enabled, trace_payload=trace_payload)

    def trace_log_path(self) -> str:
        return _resolve_plan_domain_log_path(
            str(QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE or ""),
            "logs/plan_domain_pipeline_trace.jsonl",
        )

    def emit_failed_plan_trace(
        self,
        *,
        payload: Mapping[str, Any] | None,
        user_id: str,
        error: Exception,
    ) -> Optional[str]:
        body = dict(payload or {}) if isinstance(payload, Mapping) else {}
        enabled = bool(
            QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED
            or bool(body.get("profile_pipeline_data"))
            or bool(body.get("profile_pipeline"))
        )
        if not enabled:
            return None

        error_details: Dict[str, Any] = {}
        status_code = 500
        error_message = str(error)
        if isinstance(error, ForgeError):
            status_code = int(error.status_code or 500)
            error_message = str(error.message or error_message or "plan_domain failed")
            if isinstance(error.details, Mapping):
                error_details = dict(error.details)

        trace_id = str(error_details.get("trace_id") or uuid.uuid4())
        trace_payload: Dict[str, Any] = {
            "trace_id": trace_id,
            "workspace_id": str(body.get("workspace_id") or ""),
            "user_id": str(user_id or ""),
            "conversation_id": str(body.get("conversation_id") or ""),
            "prompt": str(body.get("prompt") or ""),
            "fast_mode": bool(body.get("fast_mode")) if body.get("fast_mode") is not None else bool(QF_PLAN_DOMAIN_FAST_MODE_DEFAULT),
            "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
            "failed": True,
            "steps": [
                {
                    "step": "plan_failed",
                    "data": {
                        "error_type": error.__class__.__name__,
                        "error_message": error_message,
                        "status_code": status_code,
                        "error_details": error_details,
                        "request_context": {
                            "workspace_id": str(body.get("workspace_id") or ""),
                            "conversation_id": str(body.get("conversation_id") or ""),
                            "vertical_norm": str(body.get("vertical_norm") or ""),
                            "base_domain_id": body.get("base_domain_id"),
                            "profile_pipeline": bool(body.get("profile_pipeline")),
                            "profile_pipeline_data": bool(body.get("profile_pipeline_data")),
                            "next_actions_async": bool(body.get("next_actions_async")),
                            "llm_id": body.get("llm_id"),
                        },
                    },
                }
            ],
        }
        self.emit_trace_log(enabled=True, trace_payload=trace_payload)
        return trace_id

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from croniter import croniter
from dateutil.rrule import rrulestr

UTC = timezone.utc


@dataclass(frozen=True)
class ScheduleWindow:
    schedule_key: str
    scheduled_for: datetime
    window_start: datetime
    window_end: datetime | None
    idempotency_key: str
    mode: str
    run_context: dict[str, Any]


class ScheduleWindowCalculator:
    def due_window(
        self,
        *,
        workflow: dict[str, Any],
        node: dict[str, Any],
        config: dict[str, Any],
        now: datetime,
    ) -> ScheduleWindow | None:
        trigger_node_id = str(node.get("id") or "").strip()
        schedule_key = str(config.get("schedule_key") or f"{workflow.get('workflow_key')}:{trigger_node_id}").strip()
        mode = str(config.get("mode") or "production").strip()
        window_start, window_end = self._window_bounds(config=config, workflow=workflow, now=now)
        if window_start is None or window_start > now:
            return None
        idempotency_key = (
            f"schedule:{workflow.get('workflow_definition_id')}:{workflow.get('workflow_version_id')}:"
            f"{trigger_node_id}:{self.storage_datetime(window_start).isoformat()}"
        )
        return ScheduleWindow(
            schedule_key=schedule_key,
            scheduled_for=window_start,
            window_start=window_start,
            window_end=window_end,
            idempotency_key=idempotency_key,
            mode=mode,
            run_context={
                "source": "schedule",
                "trigger_type": "schedule_trigger",
                "trigger_node_id": trigger_node_id,
                "schedule_key": schedule_key,
                "scheduled_for": self.storage_datetime(window_start).isoformat(),
                "window_start": self.storage_datetime(window_start).isoformat(),
                "window_end": self.storage_datetime(window_end).isoformat() if window_end is not None else None,
                "schedule": config,
            },
        )

    def _window_bounds(
        self,
        *,
        config: dict[str, Any],
        workflow: dict[str, Any],
        now: datetime,
    ) -> tuple[datetime | None, datetime | None]:
        if config.get("interval_minutes") is not None:
            return self._interval_window(minutes=int(config["interval_minutes"]), now=now)
        if config.get("cron"):
            return self._cron_window(cron_text=str(config["cron"]), now=now)
        if config.get("rrule"):
            return self._rrule_window(rrule_text=str(config["rrule"]), config=config, workflow=workflow, now=now)
        return None, None

    def _interval_window(self, *, minutes: int, now: datetime) -> tuple[datetime | None, datetime | None]:
        if minutes < 1:
            return None, None
        interval = timedelta(minutes=minutes)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        elapsed = int((now - epoch).total_seconds())
        start = epoch + timedelta(seconds=(elapsed // int(interval.total_seconds())) * int(interval.total_seconds()))
        return start, start + interval

    def _cron_window(self, *, cron_text: str, now: datetime) -> tuple[datetime | None, datetime | None]:
        previous_start = self.as_utc(croniter(cron_text, now + timedelta(seconds=1)).get_prev(datetime))
        next_start = self.as_utc(croniter(cron_text, previous_start + timedelta(seconds=1)).get_next(datetime))
        return previous_start, next_start

    def _rrule_window(
        self,
        *,
        rrule_text: str,
        config: dict[str, Any],
        workflow: dict[str, Any],
        now: datetime,
    ) -> tuple[datetime | None, datetime | None]:
        dtstart = self._schedule_start(config=config, workflow=workflow, now=now)
        rule = rrulestr(rrule_text, dtstart=dtstart)
        previous_start = rule.before(now + timedelta(seconds=1), inc=True)
        if previous_start is None:
            return None, None
        next_start = rule.after(previous_start, inc=False)
        return self.as_utc(previous_start), self.as_utc(next_start) if next_start is not None else None

    def _schedule_start(self, *, config: dict[str, Any], workflow: dict[str, Any], now: datetime) -> datetime:
        explicit_start = config.get("start_at") or config.get("dtstart")
        if explicit_start:
            return self.as_utc(explicit_start)
        published_at = workflow.get("published_at") or workflow.get("created_at")
        if published_at:
            return self.as_utc(published_at)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def as_utc(value: Any) -> datetime:
        if isinstance(value, str):
            text = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
        elif isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.now(UTC)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def storage_datetime(value: datetime) -> datetime:
        return value.astimezone(UTC).replace(tzinfo=None, microsecond=0)

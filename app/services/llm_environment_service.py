from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    AWS_SESSION_TOKEN,
    LLM_INSTANCE_ID,
    LLM_STATUS_CACHE_SECONDS,
)
from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)

try:
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:  # pragma: no cover - fallback when botocore is unavailable
    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        response: Dict[str, Any] = {}


_STATE_MAP = {
    "pending": "starting",
    "running": "running",
    "stopping": "stopping",
    "stopped": "stopped",
}


def _build_ec2_client(
    *,
    region: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
):
    try:
        import boto3
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise ForgeError("boto3 is required for LLM environment control", status_code=500) from exc
    return boto3.client(
        "ec2",
        region_name=region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_session_token=aws_session_token,
    )


class LLMEnvironmentService:
    """
    Service for controlling the single configured LLM EC2 instance.

    IAM policy example:
    {
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": [
            "ec2:StartInstances",
            "ec2:StopInstances",
            "ec2:DescribeInstances"
          ],
          "Resource": "arn:aws:ec2:REGION:ACCOUNT_ID:instance/INSTANCE_ID"
        }
      ]
    }
    """

    def __init__(
        self,
        *,
        instance_id: Optional[str] = None,
        region: Optional[str] = None,
        cache_seconds: Optional[int] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        ec2_client: Any = None,
        time_fn: Any = None,
    ) -> None:
        self.instance_id = (instance_id if instance_id is not None else LLM_INSTANCE_ID).strip()
        self.region = (region if region is not None else AWS_REGION).strip() or "us-east-1"
        self.cache_seconds = int(cache_seconds if cache_seconds is not None else LLM_STATUS_CACHE_SECONDS or 5)
        self.aws_access_key_id = (
            aws_access_key_id if aws_access_key_id is not None else AWS_ACCESS_KEY_ID
        ).strip()
        self.aws_secret_access_key = (
            aws_secret_access_key if aws_secret_access_key is not None else AWS_SECRET_ACCESS_KEY
        ).strip()
        self.aws_session_token = (
            aws_session_token if aws_session_token is not None else AWS_SESSION_TOKEN
        )
        self._time_fn = time_fn or time.time
        self._cached_status: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0.0
        self._last_logged_raw_state: Optional[str] = None

        if not self.instance_id:
            raise ForgeError("LLM_INSTANCE_ID is required", status_code=500)
        if ec2_client is None and (not self.aws_access_key_id or not self.aws_secret_access_key):
            raise ForgeError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required",
                status_code=500,
            )

        self._ec2 = ec2_client or _build_ec2_client(
            region=self.region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            aws_session_token=self.aws_session_token,
        )

    def start_instance(self) -> Dict[str, Any]:
        logger.info("LLM instance start requested instance_id=%s", self.instance_id)
        try:
            self._ec2.start_instances(InstanceIds=[self.instance_id])
            self._invalidate_cache()
            return self.get_instance_status(force_refresh=True)
        except Exception as exc:
            raise self._translate_aws_error("Failed to start LLM instance", exc)

    def stop_instance(self) -> Dict[str, Any]:
        logger.info("LLM instance stop requested instance_id=%s", self.instance_id)
        try:
            self._ec2.stop_instances(InstanceIds=[self.instance_id])
            self._invalidate_cache()
            return self.get_instance_status(force_refresh=True)
        except Exception as exc:
            raise self._translate_aws_error("Failed to stop LLM instance", exc)

    def get_instance_status(self, *, force_refresh: bool = False) -> Dict[str, Any]:
        now = float(self._time_fn())
        if (
            not force_refresh
            and self._cached_status is not None
            and (now - self._cached_at) < max(0, self.cache_seconds)
        ):
            return dict(self._cached_status)

        try:
            status = self._fetch_instance_status()
            self._cached_status = status
            self._cached_at = now

            raw_state = status.get("rawState")
            if raw_state != self._last_logged_raw_state:
                logger.info(
                    "LLM instance state transition instance_id=%s raw=%s mapped=%s",
                    self.instance_id,
                    raw_state,
                    status.get("state"),
                )
                self._last_logged_raw_state = str(raw_state)

            return dict(status)
        except Exception as exc:
            raise self._translate_aws_error("Failed to fetch LLM instance status", exc)

    def _fetch_instance_status(self) -> Dict[str, Any]:
        response = self._ec2.describe_instances(InstanceIds=[self.instance_id])
        reservations = response.get("Reservations") or []
        instances = reservations[0].get("Instances") if reservations else None
        instance = instances[0] if instances else None
        if not instance:
            raise ForgeError("LLM instance not found", status_code=404)

        raw_state = str((instance.get("State") or {}).get("Name") or "unknown").lower()
        mapped_state = _STATE_MAP.get(raw_state, "error")
        return {
            "state": mapped_state,
            "publicIp": instance.get("PublicIpAddress"),
            "instanceId": self.instance_id,
            "rawState": raw_state,
        }

    def _invalidate_cache(self) -> None:
        self._cached_status = None
        self._cached_at = 0.0

    def _translate_aws_error(self, message: str, exc: Exception) -> ForgeError:
        if isinstance(exc, ForgeError):
            return exc
        if isinstance(exc, ClientError):
            error = getattr(exc, "response", {}).get("Error", {})
            code = str(error.get("Code") or "ClientError")
            details = {"code": code, "message": error.get("Message", str(exc))}
            if code in {"InvalidInstanceID.NotFound"}:
                return ForgeError(message, status_code=404, details=details)
            if code in {"UnauthorizedOperation", "AuthFailure"}:
                return ForgeError(message, status_code=403, details=details)
            return ForgeError(message, status_code=502, details=details)
        if isinstance(exc, BotoCoreError):
            return ForgeError(message, status_code=502, details={"message": str(exc)})
        logger.exception("%s instance_id=%s", message, self.instance_id)
        return ForgeError(message, status_code=500, details={"message": str(exc)})

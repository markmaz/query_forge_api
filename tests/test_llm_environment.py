from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.llm_environment_service import LLMEnvironmentService


class FakeEC2Client:
    def __init__(self, *, state: str = "stopped", public_ip: Optional[str] = None) -> None:
        self.state = state
        self.public_ip = public_ip
        self.start_calls: list[list[str]] = []
        self.stop_calls: list[list[str]] = []
        self.describe_calls = 0

    def start_instances(self, *, InstanceIds: list[str]) -> Dict[str, Any]:
        self.start_calls.append(InstanceIds)
        self.state = "pending"
        return {}

    def stop_instances(self, *, InstanceIds: list[str]) -> Dict[str, Any]:
        self.stop_calls.append(InstanceIds)
        self.state = "stopping"
        return {}

    def describe_instances(self, *, InstanceIds: list[str]) -> Dict[str, Any]:
        self.describe_calls += 1
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": InstanceIds[0],
                            "State": {"Name": self.state},
                            "PublicIpAddress": self.public_ip,
                        }
                    ]
                }
            ]
        }


def test_start_instance_calls_ec2_start_instances_with_configured_id() -> None:
    fake = FakeEC2Client(state="stopped")
    svc = LLMEnvironmentService(
        instance_id="i-123",
        region="us-east-1",
        ec2_client=fake,
        cache_seconds=5,
    )

    result = svc.start_instance()
    assert fake.start_calls == [["i-123"]]
    assert result["instanceId"] == "i-123"
    assert result["state"] == "starting"
    assert result["rawState"] == "pending"


def test_stop_instance_calls_ec2_stop_instances() -> None:
    fake = FakeEC2Client(state="running")
    svc = LLMEnvironmentService(
        instance_id="i-123",
        region="us-east-1",
        ec2_client=fake,
        cache_seconds=5,
    )

    result = svc.stop_instance()
    assert fake.stop_calls == [["i-123"]]
    assert result["state"] == "stopping"
    assert result["rawState"] == "stopping"


@pytest.mark.parametrize(
    ("aws_state", "ui_state"),
    [
        ("pending", "starting"),
        ("running", "running"),
        ("stopping", "stopping"),
        ("stopped", "stopped"),
        ("terminated", "error"),
    ],
)
def test_get_instance_status_maps_aws_states(aws_state: str, ui_state: str) -> None:
    fake = FakeEC2Client(state=aws_state, public_ip="1.2.3.4")
    svc = LLMEnvironmentService(
        instance_id="i-abc",
        region="us-east-1",
        ec2_client=fake,
        cache_seconds=5,
    )

    status = svc.get_instance_status(force_refresh=True)
    assert status["state"] == ui_state
    assert status["rawState"] == aws_state
    assert status["publicIp"] == "1.2.3.4"
    assert status["instanceId"] == "i-abc"


def test_get_instance_status_uses_cache_window() -> None:
    now = {"value": 100.0}
    fake = FakeEC2Client(state="running")
    svc = LLMEnvironmentService(
        instance_id="i-cache",
        region="us-east-1",
        ec2_client=fake,
        cache_seconds=5,
        time_fn=lambda: now["value"],
    )

    first = svc.get_instance_status()
    second = svc.get_instance_status()
    assert first["state"] == "running"
    assert second["state"] == "running"
    assert fake.describe_calls == 1

    now["value"] = 106.0
    third = svc.get_instance_status()
    assert third["state"] == "running"
    assert fake.describe_calls == 2


def test_missing_instance_id_raises_service_error() -> None:
    fake = FakeEC2Client()
    with pytest.raises(ForgeError, match="LLM_INSTANCE_ID is required") as exc:
        LLMEnvironmentService(
            instance_id="",
            region="us-east-1",
            ec2_client=fake,
            cache_seconds=5,
        )
    assert exc.value.status_code == 500


def test_missing_aws_credentials_raises_service_error_without_client() -> None:
    with pytest.raises(
        ForgeError, match="AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required"
    ) as exc:
        LLMEnvironmentService(
            instance_id="i-abc",
            region="us-east-1",
            aws_access_key_id="",
            aws_secret_access_key="",
            cache_seconds=5,
        )
    assert exc.value.status_code == 500

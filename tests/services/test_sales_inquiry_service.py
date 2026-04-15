from __future__ import annotations

import uuid

import pytest

import app.services.sales_inquiry_service as sales_inquiry_service
from app.services.sales_inquiry_service import SalesInquiryService
from tests._support.fakes import FakeForgeQueryPort


def _payload() -> dict[str, object]:
    return {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "work_email": "ada@example.com",
        "phone": "+1-555-0100",
        "organization": "Analytical Engines Inc",
        "role_title": "CTO",
        "primary_interest": "Data Integration",
        "primary_data_model": "Snowflake",
        "problem_statement": "We need a unified semantic layer.",
        "consent_contact": True,
        "source": "marketing_site",
        "ip_address": "127.0.0.1",
        "user_agent": "pytest",
    }


def test_create_inquiry_swallows_expected_notification_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = FakeForgeQueryPort()
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")

    monkeypatch.setattr(sales_inquiry_service.uuid, "uuid4", lambda: fixed_uuid)
    monkeypatch.setattr(sales_inquiry_service, "SALES_INQUIRY_EMAIL", "sales@example.com")
    monkeypatch.setattr(sales_inquiry_service, "get_logo", lambda: "logo")
    monkeypatch.setattr(
        sales_inquiry_service,
        "send_email",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("smtp unavailable")),
    )

    inquiry_id = SalesInquiryService(sql=sql).create_inquiry(_payload())

    assert inquiry_id == fixed_uuid
    assert len(sql.write_calls) == 1
    assert sql.write_calls[0].params["work_email"] == "ada@example.com"


def test_create_inquiry_surfaces_unexpected_notification_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = FakeForgeQueryPort()

    monkeypatch.setattr(sales_inquiry_service, "SALES_INQUIRY_EMAIL", "sales@example.com")
    monkeypatch.setattr(sales_inquiry_service, "get_logo", lambda: "logo")
    monkeypatch.setattr(
        sales_inquiry_service,
        "send_email",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected mail bug")),
    )

    with pytest.raises(AssertionError, match="unexpected mail bug"):
        SalesInquiryService(sql=sql).create_inquiry(_payload())

    assert len(sql.write_calls) == 1

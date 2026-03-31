import uuid

import app.features.auth.public_api as public_sales_inquiry
from app.config import ERROR_VALIDATION_URL, THANK_YOU_REDIRECT


def test_public_sales_inquiry_form_success(client, monkeypatch):
    captured = []
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")

    def _create(self, payload):
        captured.append(payload)
        return fixed_uuid

    monkeypatch.setattr(public_sales_inquiry.SalesInquiryService, "create_inquiry", _create)

    data = {
        "first_name": "  Ada ",
        "last_name": " Lovelace ",
        "work_email": " ADA@Example.Com ",
        "phone": " +1-555-0100 ",
        "organization": " Analytical Engines Inc ",
        "role_title": " CTO ",
        "primary_interest": " Data Integration ",
        "primary_data_model": " Snowflake ",
        "problem_statement": " We need a unified semantic layer. ",
        "consent_contact": "on",
        "source": " marketing_site ",
    }

    resp = client.post(
        "/api/v1/public/sales-inquiry",
        data=data,
        content_type="application/x-www-form-urlencoded",
    )

    assert resp.status_code == 303
    assert resp.headers["Location"].endswith(THANK_YOU_REDIRECT)

    assert len(captured) == 1
    payload = captured[0]
    assert payload["first_name"] == "Ada"
    assert payload["last_name"] == "Lovelace"
    assert payload["work_email"] == "ada@example.com"
    assert payload["phone"] == "+1-555-0100"
    assert payload["organization"] == "Analytical Engines Inc"
    assert payload["role_title"] == "CTO"
    assert payload["primary_interest"] == "Data Integration"
    assert payload["primary_data_model"] == "Snowflake"
    assert payload["problem_statement"] == "We need a unified semantic layer."
    assert payload["consent_contact"] is True
    assert payload["source"] == "marketing_site"


def test_public_sales_inquiry_validation_error(client):
    resp = client.post(
        "/api/v1/public/sales-inquiry",
        data={"first_name": "Ada"},
        content_type="application/x-www-form-urlencoded",
    )
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith(ERROR_VALIDATION_URL)

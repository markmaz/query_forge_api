from __future__ import annotations

from app.factory import try_get_json_body


class _Request:
    def __init__(self, payload):
        self._payload = payload

    def get_json(self, silent: bool = True):
        assert silent is True
        return self._payload


def test_try_get_json_body_scrubs_nested_secret_fields() -> None:
    payload = {
        "username": "user@example.com",
        "password": "plain-text",
        "profile": {
            "api_key": "abc123",
            "client_secret": "top-secret",
            "policy_key": "keep-visible",
        },
        "destinations": [
            {"webhook_url": "https://secret.example.com/hook", "name": "alerts"},
            {"nested": {"refresh_token": "refresh-me", "token_label": "visible-name"}},
        ],
    }

    scrubbed = try_get_json_body(_Request(payload))

    assert scrubbed == {
        "username": "user@example.com",
        "password": "*****",
        "profile": {
            "api_key": "*****",
            "client_secret": "*****",
            "policy_key": "keep-visible",
        },
        "destinations": [
            {"webhook_url": "*****", "name": "alerts"},
            {"nested": {"refresh_token": "*****", "token_label": "visible-name"}},
        ],
    }
    assert payload["password"] == "plain-text"
    assert payload["profile"]["api_key"] == "abc123"


def test_try_get_json_body_handles_top_level_list_payload() -> None:
    payload = [
        {"Authorization": "Bearer secret"},
        {"access_token": "secret-token"},
    ]

    scrubbed = try_get_json_body(_Request(payload))

    assert scrubbed == [
        {"Authorization": "*****"},
        {"access_token": "*****"},
    ]


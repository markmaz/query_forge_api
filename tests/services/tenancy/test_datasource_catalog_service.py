from __future__ import annotations

from app.services.tenancy.datasource_catalog_service import DatasourceCatalogService


class _StubSQL:
    def __init__(self, rows):
        self._rows = rows

    def execute_query_mappings(self, _query: str, _params=None):
        return list(self._rows)


def test_load_executor_config_by_name_decrypts_encrypted_password(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )

    service = DatasourceCatalogService(
        sql=_StubSQL(
            [
                {
                    "id": 3,
                    "organization_id": "org-1",
                    "name": "primary",
                    "slug": "primary",
                    "type": "snowflake",
                    "secret_ref": None,
                    "config_json": {"account": "acct", "password_encrypted": "enc::secret-1"},
                    "is_active": 1,
                }
            ]
        )
    )

    cfg = service.load_executor_config_by_name(name="primary")
    assert cfg is not None
    assert cfg["password"] == "secret-1"
    assert cfg["type"] == "snowflake"

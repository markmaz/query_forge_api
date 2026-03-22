from __future__ import annotations

from typing import Any, Dict, Iterable

from app.utils.encryption import decrypt_secret, encrypt_secret

_MASKED_SECRET = "******"

_SENSITIVE_FIELDS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "databricks": ("token", "client_id", "client_secret"),
    "snowflake": ("password", "private_key_pem", "private_key_passphrase"),
    "mysql": ("password",),
    "postgres": ("password",),
    "bigquery": ("password",),
}


def encrypt_datasource_config(
    datasource_type: str,
    config: Dict[str, Any] | None,
    *,
    existing_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    out = dict(config or {})
    existing = dict(existing_config or {})
    active_fields = set(_active_sensitive_fields(datasource_type, out))
    for field in _sensitive_fields(datasource_type):
        encrypted_field = f"{field}_encrypted"
        if field not in active_fields:
            out.pop(field, None)
            out.pop(encrypted_field, None)
            continue
        plaintext = str(out.get(field) or "").strip()
        if plaintext == _MASKED_SECRET and existing.get(encrypted_field):
            out.pop(field, None)
            out[encrypted_field] = existing[encrypted_field]
            continue
        if not plaintext:
            out.pop(field, None)
            if existing.get(encrypted_field) and field not in out and encrypted_field not in out:
                out[encrypted_field] = existing[encrypted_field]
            continue
        ciphertext = encrypt_secret(plaintext)
        if not ciphertext:
            continue
        if ciphertext == plaintext:
            continue
        out[encrypted_field] = ciphertext
        out.pop(field, None)
    return out


def decrypt_datasource_config(datasource_type: str, config: Dict[str, Any] | None) -> Dict[str, Any]:
    out = dict(config or {})
    for field in _sensitive_fields(datasource_type):
        encrypted_field = f"{field}_encrypted"
        encrypted_value = str(out.get(encrypted_field) or "").strip()
        plaintext = str(out.get(field) or "").strip()
        if plaintext or not encrypted_value:
            continue
        decrypted = decrypt_secret(encrypted_value)
        if decrypted:
            out[field] = decrypted
    return out


def mask_datasource_config(datasource_type: str, config: Dict[str, Any] | None) -> Dict[str, Any]:
    out = dict(config or {})
    for field in _sensitive_fields(datasource_type):
        encrypted_field = f"{field}_encrypted"
        plaintext = str(out.get(field) or "").strip()
        encrypted_value = str(out.get(encrypted_field) or "").strip()
        if plaintext or encrypted_value:
            out[field] = _MASKED_SECRET
        else:
            out.pop(field, None)
        out.pop(encrypted_field, None)
    return out


def _sensitive_fields(datasource_type: str) -> Iterable[str]:
    return _SENSITIVE_FIELDS_BY_TYPE.get(str(datasource_type or "").strip().lower(), ())


def _active_sensitive_fields(datasource_type: str, config: Dict[str, Any]) -> Iterable[str]:
    dtype = str(datasource_type or "").strip().lower()
    if dtype == "databricks":
        auth_method = str(config.get("auth_method") or "").strip().lower()
        if auth_method == "oauth_client_credentials":
            return ("client_id", "client_secret")
        return ("token",)

    if dtype != "snowflake":
        return _sensitive_fields(dtype)

    auth_method = str(config.get("auth_method") or "").strip().lower()
    if auth_method == "rsa_key":
        return ("private_key_pem", "private_key_passphrase")
    if auth_method == "externalbrowser":
        return ()
    return ("password",)

import os
import pytest
from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("QF_ENCRYPTION_KEY", key)

    import importlib
    import app.utils.encryption as encryption
    importlib.reload(encryption)

    plaintext = "sk-test-api-key-12345"
    encrypted = encryption.encrypt_api_key(plaintext)
    assert encrypted != plaintext
    assert encrypted is not None

    decrypted = encryption.decrypt_api_key(encrypted)
    assert decrypted == plaintext


def test_encrypt_empty_returns_none(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("QF_ENCRYPTION_KEY", key)
    import importlib
    import app.utils.encryption as encryption
    importlib.reload(encryption)

    assert encryption.encrypt_api_key("") is None
    assert encryption.encrypt_api_key(None) is None


def test_mask_api_key_short():
    from app.utils.encryption import mask_api_key
    assert mask_api_key("sk-abc") == "sk-***"


def test_mask_api_key_long():
    from app.utils.encryption import mask_api_key
    result = mask_api_key("sk-1234567890abcdef")
    assert result.endswith("****")
    assert "sk-" in result


def test_mask_api_key_none():
    from app.utils.encryption import mask_api_key
    assert mask_api_key(None) is None
    assert mask_api_key("") is None


def test_decrypt_invalid_ciphertext_returns_none(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("QF_ENCRYPTION_KEY", key)
    import importlib
    import app.utils.encryption as encryption
    importlib.reload(encryption)

    # Corrupted ciphertext should return None gracefully
    result = encryption.decrypt_api_key("this-is-not-valid-fernet-ciphertext")
    assert result is None

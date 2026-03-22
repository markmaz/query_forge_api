from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_fernet = None
_FERNET_INITIALIZED = False  # add this
_PRIMARY_ENV_VAR = "QF_ENCRYPTION_KEY"


def _get_fernet():
    global _fernet, _FERNET_INITIALIZED
    if _FERNET_INITIALIZED:
        return _fernet  # returns None if key was invalid (cached)
    _FERNET_INITIALIZED = True
    from cryptography.fernet import Fernet
    key = os.getenv(_PRIMARY_ENV_VAR, "").strip()
    if not key:
        logger.warning("%s is not set; secret encryption disabled", _PRIMARY_ENV_VAR)
        return None
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception:
        logger.error("Invalid %s; secret encryption disabled", _PRIMARY_ENV_VAR)
        return None


def is_secret_encryption_available() -> bool:
    return _get_fernet() is not None


def encrypt_api_key(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a plaintext API key. Returns None if key is empty or encryption unavailable."""
    text = str(plaintext or "").strip()
    if not text:
        return None
    f = _get_fernet()
    if f is None:
        logger.warning("Fernet unavailable; storing API key unencrypted")
        return text
    try:
        return f.encrypt(text.encode()).decode()
    except Exception:
        logger.exception("Failed to encrypt API key")
        return None


def decrypt_api_key(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt an encrypted API key. Returns None if decryption fails."""
    text = str(ciphertext or "").strip()
    if not text:
        return None
    f = _get_fernet()
    if f is None:
        return text  # stored unencrypted
    try:
        return f.decrypt(text.encode()).decode()
    except Exception:
        logger.exception("Failed to decrypt API key")
        return None


def encrypt_secret(plaintext: Optional[str]) -> Optional[str]:
    """Generic Fernet secret encryption helper backed by the LLM encryption key."""
    return encrypt_api_key(plaintext)


def decrypt_secret(ciphertext: Optional[str]) -> Optional[str]:
    """Generic Fernet secret decryption helper backed by the LLM encryption key."""
    return decrypt_api_key(ciphertext)


def mask_api_key(plaintext: Optional[str]) -> Optional[str]:
    """Return a masked version for display: first 6 chars + ****."""
    text = str(plaintext or "").strip()
    if not text:
        return None
    if len(text) <= 6:
        return text[:3] + "***"
    return text[:6] + "..." + "****"

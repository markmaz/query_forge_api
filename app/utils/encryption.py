from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_fernet = None
_FERNET_INITIALIZED = False  # add this


def _get_fernet():
    global _fernet, _FERNET_INITIALIZED
    if _FERNET_INITIALIZED:
        return _fernet  # returns None if key was invalid (cached)
    _FERNET_INITIALIZED = True
    from cryptography.fernet import Fernet
    key = os.getenv("QF_LLM_ENCRYPTION_KEY", "").strip()
    if not key:
        logger.warning("QF_LLM_ENCRYPTION_KEY is not set; API key encryption disabled")
        return None
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception:
        logger.error("Invalid QF_LLM_ENCRYPTION_KEY; API key encryption disabled")
        return None


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


def mask_api_key(plaintext: Optional[str]) -> Optional[str]:
    """Return a masked version for display: first 6 chars + ****."""
    text = str(plaintext or "").strip()
    if not text:
        return None
    if len(text) <= 6:
        return text[:3] + "***"
    return text[:6] + "..." + "****"

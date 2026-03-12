from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SecretResolver:
    """Resolves datasource ``secret_ref`` values.

    Supported forms:
    - ``env:VAR_NAME``

    Unsupported forms (currently logged and ignored):
    - ``vault:...``
    - ``kms:...``
    """

    def resolve(self, secret_ref: Optional[str]) -> Optional[str]:
        ref = str(secret_ref or "").strip()
        if not ref:
            return None

        if ref.startswith("env:"):
            env_key = ref.split(":", 1)[1].strip()
            if not env_key:
                return None
            return os.getenv(env_key)

        if ref.startswith("vault:") or ref.startswith("kms:"):
            logger.warning("Secret resolver does not support '%s' yet; returning no secret", ref.split(":", 1)[0])
            return None

        logger.warning("Unknown secret_ref format: %s", ref)
        return None

    def inject_if_missing(self, config: dict[str, Any], *, secret_ref: Optional[str], key: str = "token") -> dict[str, Any]:
        """Inject a resolved secret into config if the target key is currently empty."""
        merged = dict(config or {})
        if merged.get(key):
            return merged
        resolved = self.resolve(secret_ref)
        if resolved:
            merged[key] = resolved
        return merged

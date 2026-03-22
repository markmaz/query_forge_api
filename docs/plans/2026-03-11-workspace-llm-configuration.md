# Workspace LLM Configuration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-workspace LLM configuration so each workspace can have multiple LLMs assigned by role (planner, ner, summarizer, query_generator, enrichment), with CRUD API, Fernet-encrypted API keys, env-var fallback, and a full frontend management UI.

**Architecture:** New `workspace_llm` table (VARCHAR workspace_id FK) → `WorkspaceLLMService` using `ForgeMetaSQL` raw SQL (consistent with tenancy services) → Flask-RestX namespace registered in `factory.py` → two frontend surfaces: a new Step 4 in the initialization wizard and a standalone management page under System Admin → Tenancy.

**Tech Stack:** Python Flask-RestX, SQLAlchemy engine (via ForgeMetaSQL), Fernet encryption (cryptography library), React 19 + Bootstrap 5.3, TanStack React Query, React Hook Form, Vitest + MSW.

---

## Audit Findings Summary

- **Migration pattern:** Raw SQL files in `query-forge-api/migrations/`. Named `YYYYMMDD_description.sql`. Use `CREATE TABLE IF NOT EXISTS` for idempotency.
- **workspace_id type:** `VARCHAR` string throughout (not INT). Use `VARCHAR(255)` FK.
- **Service pattern:** `ForgeMetaSQL().execute_query_mappings(sql, params)` for reads, `execute_write(sql, params)` for writes. Dict-based returns. See `DatasourceCatalogService`.
- **Route pattern:** `Namespace`, `ForgeResource`, `@token_required`, try/except with `ForgeError`. See `workspace_routes.py`.
- **Encryption:** No existing pattern — introduce Fernet from `cryptography`. Key from `QF_ENCRYPTION_KEY` env var.
- **LLM env vars:** `VLLM_BASE_URL` + `VLLM_MODEL` (planner/default), `SEMANTIC_LLM_ENDPOINT` + `SEMANTIC_LLM_MODEL` (ner/summarizer), `SEMANTIC_PLAN_LLM_MODEL` (planner alt). Fallback maps these to roles.
- **Unique constraint:** MySQL doesn't support partial unique indexes. Enforce "one active LLM per role per workspace" in service layer.
- **Frontend wizard:** `CustomerInitializationPage.tsx` has 4 steps (WizardStep: `1|2|3|4`). Current Step 4 = "Bind + Confirm". New Step 4 = LLMs (optional), Step 5 = "Bind + Confirm".
- **Frontend admin pattern:** `system-admin/api/` → `system-admin/hooks/` → `system-admin/ui/tenancy/` page. See `adminTenancyApi.ts` and `useAdminTenancy.ts`.

---

## Task 1: LLM Role and Provider Constants

**Files:**
- Create: `query-forge-api/app/constants/__init__.py`
- Create: `query-forge-api/app/constants/llm_roles.py`

**Step 1: Write the failing test**

```python
# tests/test_llm_constants.py
from app.constants.llm_roles import LLMRole, LLMProvider


def test_llm_role_all_contains_all_roles():
    assert LLMRole.PLANNER in LLMRole.ALL
    assert LLMRole.NER in LLMRole.ALL
    assert LLMRole.SUMMARIZER in LLMRole.ALL
    assert LLMRole.QUERY_GENERATOR in LLMRole.ALL
    assert LLMRole.ENRICHMENT in LLMRole.ALL
    assert len(LLMRole.ALL) == 5


def test_llm_provider_all_contains_supported_providers():
    assert LLMProvider.OPENAI in LLMProvider.ALL
    assert LLMProvider.ANTHROPIC in LLMProvider.ALL
    assert LLMProvider.AZURE_OPENAI in LLMProvider.ALL
    assert LLMProvider.OLLAMA in LLMProvider.ALL
    assert LLMProvider.GENERIC in LLMProvider.ALL
    assert len(LLMProvider.ALL) == 5
```

**Step 2: Run test to verify it fails**

```bash
cd query-forge-api
pytest tests/test_llm_constants.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`query-forge-api/app/constants/__init__.py`:
```python
```

`query-forge-api/app/constants/llm_roles.py`:
```python
from __future__ import annotations


class LLMRole:
    PLANNER = "planner"
    NER = "ner"
    SUMMARIZER = "summarizer"
    QUERY_GENERATOR = "query_generator"
    ENRICHMENT = "enrichment"

    ALL = [PLANNER, NER, SUMMARIZER, QUERY_GENERATOR, ENRICHMENT]

    DISPLAY_NAMES = {
        PLANNER: "Planner",
        NER: "Named Entity Recognition",
        SUMMARIZER: "Summarizer",
        QUERY_GENERATOR: "Query Generator",
        ENRICHMENT: "Enrichment",
    }


class LLMProvider:
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"
    GENERIC = "generic"

    ALL = [OPENAI, ANTHROPIC, AZURE_OPENAI, OLLAMA, GENERIC]

    DISPLAY_NAMES = {
        OPENAI: "OpenAI",
        ANTHROPIC: "Anthropic",
        AZURE_OPENAI: "Azure OpenAI",
        OLLAMA: "Ollama (local)",
        GENERIC: "Generic (OpenAI-compatible)",
    }
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_llm_constants.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add query-forge-api/app/constants/__init__.py query-forge-api/app/constants/llm_roles.py query-forge-api/tests/test_llm_constants.py
git commit -m "feat: add LLMRole and LLMProvider constants"
```

---

## Task 2: Fernet Encryption Helper

**Files:**
- Create: `query-forge-api/app/utils/encryption.py`
- Test: `query-forge-api/tests/test_encryption.py`

**Step 1: Write the failing test**

```python
# tests/test_encryption.py
import os
import pytest
from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("QF_ENCRYPTION_KEY", key)

    from app.utils import encryption
    import importlib
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
    from app.utils import encryption
    import importlib
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
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_encryption.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Verify cryptography library is available**

```bash
pip show cryptography
```
If not installed: `pip install cryptography` and add to requirements.

**Step 4: Write minimal implementation**

`query-forge-api/app/utils/encryption.py`:
```python
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    from cryptography.fernet import Fernet
    key = os.getenv("QF_ENCRYPTION_KEY", "").strip()
    if not key:
        logger.warning("QF_ENCRYPTION_KEY is not set; API key encryption disabled")
        return None
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception:
        logger.exception("Invalid QF_ENCRYPTION_KEY; API key encryption disabled")
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
```

Note: `_fernet` is module-level for performance but tests use `importlib.reload` to reset state.

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_encryption.py -v
```
Expected: PASS

**Step 6: Commit**

```bash
git add query-forge-api/app/utils/encryption.py query-forge-api/tests/test_encryption.py
git commit -m "feat: add Fernet encryption helper for LLM API keys"
```

---

## Task 3: Database Migration

**Files:**
- Create: `query-forge-api/migrations/20260311_add_workspace_llm.sql`

**Step 1: Write the migration**

```sql
-- Workspace LLM configuration
-- Date: 2026-03-11
-- Adds workspace_llm table for per-workspace LLM role assignment.
-- workspace_id is VARCHAR (matches existing workspace identity pattern).
-- One active LLM per role per workspace enforced in service layer (MySQL
-- does not support partial unique indexes without expression columns).

CREATE TABLE IF NOT EXISTS `workspace_llm` (
  `id`                bigint unsigned NOT NULL AUTO_INCREMENT,
  `workspace_id`      varchar(255) NOT NULL,
  `name`              varchar(255) NOT NULL,
  `provider`          varchar(64) NOT NULL,
  `model_name`        varchar(255) NOT NULL,
  `role`              varchar(64) NOT NULL,
  `api_key_encrypted` text DEFAULT NULL,
  `endpoint_url`      varchar(500) DEFAULT NULL,
  `is_active`         tinyint(1) NOT NULL DEFAULT '1',
  `config_json`       text DEFAULT NULL,
  `created_at`        timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_workspace_llm_workspace` (`workspace_id`),
  KEY `ix_workspace_llm_workspace_role` (`workspace_id`, `role`),
  KEY `ix_workspace_llm_active` (`workspace_id`, `is_active`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci;
```

**Step 2: Verify migration is ready**

Review the SQL for correctness. No automated test — migration runs against live DB.

**Step 3: Apply migration**

```bash
# From project root, apply directly to MySQL:
mysql -u $DB_USER -p$DB_PASSWORD -h $DB_HOST $DB_NAME < query-forge-api/migrations/20260311_add_workspace_llm.sql
```

Or using a DB client. Verify with: `DESCRIBE workspace_llm;`

**Step 4: Commit**

```bash
git add query-forge-api/migrations/20260311_add_workspace_llm.sql
git commit -m "feat: add workspace_llm migration"
```

---

## Task 4: WorkspaceLLMService

**Files:**
- Create: `query-forge-api/app/services/tenancy/workspace_llm_service.py`
- Test: `query-forge-api/tests/services/tenancy/test_workspace_llm_service.py`

**Step 1: Write the failing tests**

```python
# tests/services/tenancy/test_workspace_llm_service.py
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_sql():
    return MagicMock()


@pytest.fixture
def service(mock_sql):
    from app.services.tenancy.workspace_llm_service import WorkspaceLLMService
    return WorkspaceLLMService(sql=mock_sql)


# ── get_all_for_workspace ──────────────────────────────────────────────────────

def test_get_all_for_workspace_returns_list(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [
        {
            "id": 1,
            "workspace_id": "ws1",
            "name": "GPT-4 Planner",
            "provider": "openai",
            "model_name": "gpt-4o",
            "role": "planner",
            "api_key_encrypted": None,
            "endpoint_url": None,
            "is_active": 1,
            "config_json": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    result = service.get_all_for_workspace("ws1")
    assert len(result) == 1
    assert result[0]["role"] == "planner"
    assert "api_key_encrypted" not in result[0]
    assert result[0]["has_api_key"] is False


def test_get_all_for_workspace_has_api_key_true(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [
        {
            "id": 2,
            "workspace_id": "ws1",
            "name": "Claude NER",
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "role": "ner",
            "api_key_encrypted": "gAAAAABenc...",
            "endpoint_url": None,
            "is_active": 1,
            "config_json": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    result = service.get_all_for_workspace("ws1")
    assert result[0]["has_api_key"] is True
    assert "api_key_encrypted" not in result[0]


# ── get_llm_for_role ──────────────────────────────────────────────────────────

def test_get_llm_for_role_returns_db_config(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [
        {
            "id": 1,
            "workspace_id": "ws1",
            "name": "GPT-4 Planner",
            "provider": "openai",
            "model_name": "gpt-4o",
            "role": "planner",
            "api_key_encrypted": "enc_key",
            "endpoint_url": None,
            "is_active": 1,
            "config_json": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    with patch("app.services.tenancy.workspace_llm_service.decrypt_api_key", return_value="sk-real"):
        result = service.get_llm_for_role("ws1", "planner")
    assert result is not None
    assert result["provider"] == "openai"
    assert result["api_key"] == "sk-real"


def test_get_llm_for_role_falls_back_to_env(service, mock_sql, monkeypatch):
    mock_sql.execute_query_mappings.return_value = []
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("VLLM_MODEL", "qwen25-7b")
    result = service.get_llm_for_role("ws1", "planner")
    assert result is not None
    assert result["provider"] == "generic"
    assert result["endpoint_url"] == "http://localhost:8000"


def test_get_llm_for_role_returns_none_when_nothing_configured(service, mock_sql, monkeypatch):
    mock_sql.execute_query_mappings.return_value = []
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    result = service.get_llm_for_role("ws1", "planner")
    assert result is None


# ── create_llm ────────────────────────────────────────────────────────────────

def test_create_llm_enforces_one_active_per_role(service, mock_sql):
    # Simulate existing active record
    mock_sql.execute_query_mappings.return_value = [{"id": 99}]
    with pytest.raises(ValueError, match="already has an active LLM"):
        service.create_llm("ws1", {
            "name": "Duplicate",
            "provider": "openai",
            "model_name": "gpt-4o",
            "role": "planner",
            "is_active": True,
        })


def test_create_llm_encrypts_api_key(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = []  # no existing active
    mock_sql.execute_write.return_value = None
    mock_sql.execute_query_mappings.side_effect = [
        [],  # check existing active
        [{"id": 1, "workspace_id": "ws1", "name": "Test", "provider": "openai",
          "model_name": "gpt-4o", "role": "planner", "api_key_encrypted": "enc",
          "endpoint_url": None, "is_active": 1, "config_json": None,
          "created_at": None, "updated_at": None}],
    ]
    with patch("app.services.tenancy.workspace_llm_service.encrypt_api_key", return_value="enc_val"):
        result = service.create_llm("ws1", {
            "name": "Test",
            "provider": "openai",
            "model_name": "gpt-4o",
            "role": "planner",
            "api_key": "sk-plaintext",
            "is_active": True,
        })
    assert result is not None


# ── API key masking ───────────────────────────────────────────────────────────

def test_masked_api_key_in_response(service, mock_sql):
    mock_sql.execute_query_mappings.return_value = [
        {
            "id": 1,
            "workspace_id": "ws1",
            "name": "Test",
            "provider": "openai",
            "model_name": "gpt-4o",
            "role": "planner",
            "api_key_encrypted": "gAAAAAB_some_encrypted_value",
            "endpoint_url": None,
            "is_active": 1,
            "config_json": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    with patch("app.services.tenancy.workspace_llm_service.decrypt_api_key", return_value="sk-1234567890abcdef"):
        result = service.get_all_for_workspace("ws1")
    # Raw key must never appear
    assert result[0].get("api_key") is None
    assert result[0].get("api_key_encrypted") is None
    # Masked key present
    assert result[0]["masked_api_key"] is not None
    assert "1234567890abcdef" not in str(result[0]["masked_api_key"])
```

**Step 2: Run tests to verify they fail**

```bash
cd query-forge-api
pytest tests/services/tenancy/test_workspace_llm_service.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Create the directory and `__init__.py` if needed**

```bash
ls query-forge-api/tests/services/tenancy/ 2>/dev/null || mkdir -p query-forge-api/tests/services/tenancy && touch query-forge-api/tests/services/tenancy/__init__.py
```

**Step 4: Write the service implementation**

`query-forge-api/app/services/tenancy/workspace_llm_service.py`:
```python
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.constants.llm_roles import LLMProvider, LLMRole
from app.ports.sql_executor import ForgeQueryPort
from app.utils.encryption import decrypt_api_key, encrypt_api_key, mask_api_key

logger = logging.getLogger(__name__)

_VALID_ROLES = set(LLMRole.ALL)
_VALID_PROVIDERS = set(LLMProvider.ALL)

_SELECT_COLS = """
    id, workspace_id, name, provider, model_name, role,
    api_key_encrypted, endpoint_url, is_active, config_json,
    created_at, updated_at
"""


class WorkspaceLLMService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    # ── public read ──────────────────────────────────────────────────────────

    def get_all_for_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        ws = str(workspace_id or "").strip()
        if not ws:
            return []
        try:
            rows = self._sql.execute_query_mappings(
                f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE workspace_id = :ws ORDER BY role, id",
                {"ws": ws},
            )
        except Exception:
            logger.exception("get_all_for_workspace failed for %s", ws)
            return []
        return [self._to_public_dict(row) for row in rows]

    def get_by_id(self, llm_id: int) -> Optional[Dict[str, Any]]:
        try:
            rows = self._sql.execute_query_mappings(
                f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
                {"id": llm_id},
            )
        except Exception:
            logger.exception("get_by_id failed for id=%s", llm_id)
            return None
        if not rows:
            return None
        return self._to_public_dict(rows[0])

    def get_llm_for_role(self, workspace_id: str, role: str) -> Optional[Dict[str, Any]]:
        """
        Returns the active LLM config for the given workspace and role.
        Falls back to environment variable config if no DB record exists.
        Returns None if neither is configured.
        The returned dict may contain a decrypted api_key for internal backend use only.
        Never return this dict via REST.
        """
        ws = str(workspace_id or "").strip()
        r = str(role or "").strip()
        if not ws or not r:
            return None

        try:
            rows = self._sql.execute_query_mappings(
                f"""
                SELECT {_SELECT_COLS} FROM workspace_llm
                WHERE workspace_id = :ws AND role = :role AND is_active = 1
                LIMIT 1
                """,
                {"ws": ws, "role": r},
            )
        except Exception:
            logger.exception("get_llm_for_role DB lookup failed ws=%s role=%s", ws, r)
            rows = []

        if rows:
            return self._to_internal_dict(rows[0])

        # Fallback to env var config
        return self._env_fallback(r)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create_llm(self, workspace_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip()
        role = str(data.get("role") or "").strip()
        provider = str(data.get("provider") or "").strip()
        name = str(data.get("name") or "").strip()
        model_name = str(data.get("model_name") or "").strip()
        is_active = bool(data.get("is_active", True))

        if not ws:
            raise ValueError("workspace_id is required")
        if not name:
            raise ValueError("name is required")
        if role not in _VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {sorted(_VALID_ROLES)}")
        if provider not in _VALID_PROVIDERS:
            raise ValueError(f"Invalid provider '{provider}'. Must be one of: {sorted(_VALID_PROVIDERS)}")
        if not model_name:
            raise ValueError("model_name is required")

        if is_active:
            self._assert_no_active_for_role(ws, role, exclude_id=None)

        api_key_plaintext = str(data.get("api_key") or "").strip() or None
        api_key_encrypted = encrypt_api_key(api_key_plaintext) if api_key_plaintext else None
        endpoint_url = str(data.get("endpoint_url") or "").strip() or None
        config_json_raw = data.get("config_json")
        config_json = json.dumps(config_json_raw) if config_json_raw else None

        self._sql.execute_write(
            """
            INSERT INTO workspace_llm
              (workspace_id, name, provider, model_name, role,
               api_key_encrypted, endpoint_url, is_active, config_json)
            VALUES
              (:ws, :name, :provider, :model_name, :role,
               :api_key_encrypted, :endpoint_url, :is_active, :config_json)
            """,
            {
                "ws": ws,
                "name": name,
                "provider": provider,
                "model_name": model_name,
                "role": role,
                "api_key_encrypted": api_key_encrypted,
                "endpoint_url": endpoint_url,
                "is_active": 1 if is_active else 0,
                "config_json": config_json,
            },
        )

        # Fetch newly created row by workspace+role+name (last inserted)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT {_SELECT_COLS} FROM workspace_llm
            WHERE workspace_id = :ws AND name = :name AND role = :role
            ORDER BY id DESC LIMIT 1
            """,
            {"ws": ws, "name": name, "role": role},
        )
        if not rows:
            raise RuntimeError("Failed to fetch newly created workspace_llm")
        return self._to_public_dict(rows[0])

    def update_llm(self, llm_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        existing_rows = self._sql.execute_query_mappings(
            f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
            {"id": llm_id},
        )
        if not existing_rows:
            raise ValueError(f"workspace_llm id={llm_id} not found")

        existing = dict(existing_rows[0])
        ws = existing["workspace_id"]

        name = str(data.get("name") or existing.get("name") or "").strip()
        provider = str(data.get("provider") or existing.get("provider") or "").strip()
        model_name = str(data.get("model_name") or existing.get("model_name") or "").strip()
        role = str(data.get("role") or existing.get("role") or "").strip()
        is_active = bool(data.get("is_active", bool(int(existing.get("is_active") or 1))))
        endpoint_url = str(data.get("endpoint_url") or existing.get("endpoint_url") or "").strip() or None

        if role not in _VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'")
        if provider not in _VALID_PROVIDERS:
            raise ValueError(f"Invalid provider '{provider}'")

        if is_active:
            self._assert_no_active_for_role(ws, role, exclude_id=llm_id)

        # API key: only update if new key provided
        api_key_plaintext = str(data.get("api_key") or "").strip() or None
        if api_key_plaintext:
            api_key_encrypted = encrypt_api_key(api_key_plaintext)
        else:
            api_key_encrypted = existing.get("api_key_encrypted")  # preserve existing

        config_json_raw = data.get("config_json")
        if config_json_raw is not None:
            config_json = json.dumps(config_json_raw) if config_json_raw else None
        else:
            config_json = existing.get("config_json")

        self._sql.execute_write(
            """
            UPDATE workspace_llm SET
              name = :name, provider = :provider, model_name = :model_name,
              role = :role, api_key_encrypted = :api_key_encrypted,
              endpoint_url = :endpoint_url, is_active = :is_active,
              config_json = :config_json
            WHERE id = :id
            """,
            {
                "name": name,
                "provider": provider,
                "model_name": model_name,
                "role": role,
                "api_key_encrypted": api_key_encrypted,
                "endpoint_url": endpoint_url,
                "is_active": 1 if is_active else 0,
                "config_json": config_json,
                "id": llm_id,
            },
        )

        updated = self._sql.execute_query_mappings(
            f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
            {"id": llm_id},
        )
        if not updated:
            raise RuntimeError(f"Failed to fetch updated workspace_llm id={llm_id}")
        return self._to_public_dict(updated[0])

    def delete_llm(self, llm_id: int) -> None:
        self._sql.execute_write(
            "DELETE FROM workspace_llm WHERE id = :id",
            {"id": llm_id},
        )

    def test_connection(self, llm_id: int) -> Dict[str, Any]:
        """
        Basic connectivity test. Resolves decrypted config and attempts a
        minimal API call. Returns { success: bool, message: str }.
        """
        rows = self._sql.execute_query_mappings(
            f"SELECT {_SELECT_COLS} FROM workspace_llm WHERE id = :id LIMIT 1",
            {"id": llm_id},
        )
        if not rows:
            return {"success": False, "message": f"LLM config id={llm_id} not found"}

        config = self._to_internal_dict(rows[0])
        provider = config.get("provider")
        endpoint = config.get("endpoint_url") or ""
        api_key = config.get("api_key") or ""
        model = config.get("model_name") or ""

        try:
            if provider == LLMProvider.OLLAMA or provider == LLMProvider.GENERIC:
                return self._test_openai_compatible(endpoint, api_key, model)
            elif provider == LLMProvider.OPENAI:
                return self._test_openai_compatible("https://api.openai.com/v1", api_key, model)
            elif provider == LLMProvider.ANTHROPIC:
                return self._test_anthropic(api_key, model)
            elif provider == LLMProvider.AZURE_OPENAI:
                return self._test_openai_compatible(endpoint, api_key, model)
            else:
                return {"success": False, "message": f"Unknown provider: {provider}"}
        except Exception as exc:
            logger.exception("test_connection failed for llm_id=%s", llm_id)
            return {"success": False, "message": str(exc)}

    # ── helpers ───────────────────────────────────────────────────────────────

    def _assert_no_active_for_role(
        self, workspace_id: str, role: str, *, exclude_id: Optional[int]
    ) -> None:
        sql = """
            SELECT id FROM workspace_llm
            WHERE workspace_id = :ws AND role = :role AND is_active = 1
        """
        params: Dict[str, Any] = {"ws": workspace_id, "role": role}
        if exclude_id is not None:
            sql += " AND id != :exclude_id"
            params["exclude_id"] = exclude_id
        sql += " LIMIT 1"
        rows = self._sql.execute_query_mappings(sql, params)
        if rows:
            raise ValueError(
                f"Workspace '{workspace_id}' already has an active LLM for role '{role}'. "
                "Deactivate it first."
            )

    def _to_public_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Safe dict for REST responses — never includes raw api_key."""
        encrypted = row.get("api_key_encrypted")
        has_api_key = bool(encrypted)
        masked = None
        if has_api_key:
            try:
                plaintext = decrypt_api_key(encrypted)
                masked = mask_api_key(plaintext) if plaintext else None
            except Exception:
                masked = "****"

        config_json = self._coerce_json(row.get("config_json"))
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "name": row.get("name"),
            "provider": row.get("provider"),
            "model_name": row.get("model_name"),
            "role": row.get("role"),
            "has_api_key": has_api_key,
            "masked_api_key": masked,
            "endpoint_url": row.get("endpoint_url"),
            "is_active": bool(int(row.get("is_active") or 0)),
            "config_json": config_json,
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        }

    def _to_internal_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Internal dict with decrypted api_key. Never return via REST."""
        encrypted = row.get("api_key_encrypted")
        api_key = decrypt_api_key(encrypted) if encrypted else None
        config_json = self._coerce_json(row.get("config_json"))
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "provider": row.get("provider"),
            "model_name": row.get("model_name"),
            "role": row.get("role"),
            "api_key": api_key,
            "endpoint_url": row.get("endpoint_url"),
            "is_active": bool(int(row.get("is_active") or 0)),
            "config_json": config_json,
        }

    def _env_fallback(self, role: str) -> Optional[Dict[str, Any]]:
        """Build LLM config from environment variables for the given role."""
        vllm_url = os.getenv("VLLM_BASE_URL", "").strip()
        vllm_model = os.getenv("VLLM_MODEL", "").strip()

        if role in (LLMRole.PLANNER, LLMRole.QUERY_GENERATOR, LLMRole.ENRICHMENT):
            endpoint = vllm_url
            model = os.getenv("SEMANTIC_PLAN_LLM_MODEL", vllm_model).strip() or vllm_model
        elif role in (LLMRole.NER, LLMRole.SUMMARIZER):
            endpoint = os.getenv("SEMANTIC_LLM_ENDPOINT", vllm_url).strip()
            model = os.getenv("SEMANTIC_LLM_MODEL", vllm_model).strip() or vllm_model
        else:
            endpoint = vllm_url
            model = vllm_model

        if not endpoint or not model:
            return None

        return {
            "provider": LLMProvider.GENERIC,
            "model_name": model,
            "role": role,
            "api_key": None,
            "endpoint_url": endpoint,
            "is_active": True,
            "config_json": None,
            "_source": "env",
        }

    @staticmethod
    def _coerce_json(value: Any) -> Optional[Dict[str, Any]]:
        if isinstance(value, dict):
            return value
        if not value:
            return None
        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _test_openai_compatible(self, endpoint: str, api_key: str, model: str) -> Dict[str, Any]:
        import httpx
        url = endpoint.rstrip("/") + "/models"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            r = httpx.get(url, headers=headers, timeout=10)
            if r.status_code < 400:
                return {"success": True, "message": f"Connected to {endpoint} (HTTP {r.status_code})"}
            return {"success": False, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def _test_anthropic(self, api_key: str, model: str) -> Dict[str, Any]:
        import httpx
        try:
            r = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key or "",
                    "anthropic-version": "2023-06-01",
                },
                timeout=10,
            )
            if r.status_code < 400:
                return {"success": True, "message": f"Anthropic API reachable (HTTP {r.status_code})"}
            return {"success": False, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}
```

**Step 5: Run tests**

```bash
pytest tests/services/tenancy/test_workspace_llm_service.py -v
```
Expected: PASS

**Step 6: Commit**

```bash
git add query-forge-api/app/services/tenancy/workspace_llm_service.py \
        query-forge-api/tests/services/tenancy/test_workspace_llm_service.py \
        query-forge-api/tests/services/tenancy/__init__.py
git commit -m "feat: add WorkspaceLLMService with encryption, fallback, and CRUD"
```

---

## Task 5: LLM Config Resolver

**Files:**
- Create: `query-forge-api/app/config/llm_resolver.py`
- Test: `query-forge-api/tests/config/test_llm_resolver.py`

**Step 1: Write the failing test**

```python
# tests/config/test_llm_resolver.py
from unittest.mock import MagicMock, patch
import pytest


def test_resolve_llm_config_returns_db_config(monkeypatch):
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = {
        "provider": "openai",
        "model_name": "gpt-4o",
        "api_key": "sk-real",
        "endpoint_url": None,
        "role": "planner",
    }
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        from app.config import llm_resolver
        import importlib
        importlib.reload(llm_resolver)
        result = llm_resolver.resolve_llm_config("ws1", "planner")
    assert result["provider"] == "openai"
    assert result["api_key"] == "sk-real"


def test_resolve_llm_config_returns_none_when_not_configured(monkeypatch):
    mock_service = MagicMock()
    mock_service.get_llm_for_role.return_value = None
    with patch("app.config.llm_resolver.WorkspaceLLMService", return_value=mock_service):
        from app.config import llm_resolver
        import importlib
        importlib.reload(llm_resolver)
        result = llm_resolver.resolve_llm_config("ws1", "ner")
    assert result is None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/config/test_llm_resolver.py -v
```

**Step 3: Write minimal implementation**

`query-forge-api/app/config/llm_resolver.py`:
```python
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def resolve_llm_config(workspace_id: str, role: str) -> Optional[Dict[str, Any]]:
    """
    Returns merged LLM config for use in the pipeline.
    DB config takes precedence over env var config.

    The returned dict may contain a decrypted api_key for internal backend use.
    NEVER return this dict via REST or write to logs.
    """
    from app.services.tenancy.workspace_llm_service import WorkspaceLLMService
    try:
        return WorkspaceLLMService().get_llm_for_role(workspace_id, role)
    except Exception:
        logger.exception("resolve_llm_config failed ws=%s role=%s", workspace_id, role)
        return None
```

**Step 4: Run tests**

```bash
cd query-forge-api && mkdir -p tests/config && touch tests/config/__init__.py
pytest tests/config/test_llm_resolver.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add query-forge-api/app/config/llm_resolver.py \
        query-forge-api/tests/config/test_llm_resolver.py \
        query-forge-api/tests/config/__init__.py
git commit -m "feat: add resolve_llm_config helper for pipeline LLM resolution"
```

---

## Task 6: Flask-RestX Routes

**Files:**
- Create: `query-forge-api/app/routes/workspace_llm_routes.py`
- Modify: `query-forge-api/app/factory.py` (add import + register namespace)
- Test: `query-forge-api/tests/routes/test_workspace_llm_routes.py`

**Step 1: Write the failing route tests**

```python
# tests/routes/test_workspace_llm_routes.py
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


def _make_llm_row(role="planner"):
    return {
        "id": 1,
        "workspace_id": "ws1",
        "name": "Test LLM",
        "provider": "openai",
        "model_name": "gpt-4o",
        "role": role,
        "has_api_key": False,
        "masked_api_key": None,
        "endpoint_url": None,
        "is_active": True,
        "config_json": None,
        "created_at": "",
        "updated_at": "",
    }


def test_get_llm_roles(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.decorators.security.auth_service.verify_token",
        lambda t: {"user_id": "u1", "roles": ["admin"]},
    )
    resp = client.get("/api/v1/llm-roles", headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, list)
    assert any(r["value"] == "planner" for r in data)


def test_get_llm_providers(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.decorators.security.auth_service.verify_token",
        lambda t: {"user_id": "u1", "roles": ["admin"]},
    )
    resp = client.get("/api/v1/llm-providers", headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert any(p["value"] == "openai" for p in data)


def test_list_workspace_llms(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.decorators.security.auth_service.verify_token",
        lambda t: {"user_id": "u1", "roles": ["admin"]},
    )
    mock_svc = MagicMock()
    mock_svc.get_all_for_workspace.return_value = [_make_llm_row()]
    with patch("app.routes.workspace_llm_routes.WorkspaceLLMService", return_value=mock_svc):
        resp = client.get("/api/v1/workspaces/ws1/llms", headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data) == 1
    assert "api_key_encrypted" not in str(data)


def test_create_workspace_llm_validates_role(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.decorators.security.auth_service.verify_token",
        lambda t: {"user_id": "u1", "roles": ["admin"]},
    )
    mock_svc = MagicMock()
    mock_svc.create_llm.side_effect = ValueError("Invalid role 'bad_role'")
    with patch("app.routes.workspace_llm_routes.WorkspaceLLMService", return_value=mock_svc):
        resp = client.post(
            "/api/v1/workspaces/ws1/llms",
            headers={**auth_headers, "Content-Type": "application/json"},
            data=json.dumps({
                "name": "Test",
                "provider": "openai",
                "model_name": "gpt-4o",
                "role": "bad_role",
            }),
        )
    assert resp.status_code == 400


def test_test_connection_endpoint(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.decorators.security.auth_service.verify_token",
        lambda t: {"user_id": "u1", "roles": ["admin"]},
    )
    mock_svc = MagicMock()
    mock_svc.test_connection.return_value = {"success": True, "message": "Connected"}
    with patch("app.routes.workspace_llm_routes.WorkspaceLLMService", return_value=mock_svc):
        resp = client.post(
            "/api/v1/workspaces/ws1/llms/1/test",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/routes/test_workspace_llm_routes.py -v
```
Expected: FAIL (namespace not registered)

**Step 3: Write the route file**

`query-forge-api/app/routes/workspace_llm_routes.py`:
```python
from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, fields

from app.constants.llm_roles import LLMProvider, LLMRole
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.forge_resource import ForgeResource
from app.services.tenancy.workspace_llm_service import WorkspaceLLMService

logger = logging.getLogger(__name__)

workspace_llm_ns = Namespace("workspace-llms", description="Workspace LLM configuration")

_llm_create_model = workspace_llm_ns.model(
    "WorkspaceLLMCreate",
    {
        "name": fields.String(required=True, description="Friendly name"),
        "provider": fields.String(required=True, description="LLM provider"),
        "model_name": fields.String(required=True, description="Model identifier"),
        "role": fields.String(required=True, description="Pipeline role"),
        "api_key": fields.String(description="API key (write-only, never returned)"),
        "endpoint_url": fields.String(description="Base URL for azure_openai or ollama"),
        "is_active": fields.Boolean(default=True),
        "config_json": fields.Raw(description="Optional extra provider config"),
    },
)

_llm_roles_ns = Namespace("llm-roles", description="Available LLM roles")
_llm_providers_ns = Namespace("llm-providers", description="Available LLM providers")


@_llm_roles_ns.route("")
class LLMRolesList(ForgeResource):
    @token_required
    def get(self):
        return [
            {"value": role, "label": LLMRole.DISPLAY_NAMES.get(role, role)}
            for role in LLMRole.ALL
        ], 200


@_llm_providers_ns.route("")
class LLMProvidersList(ForgeResource):
    @token_required
    def get(self):
        return [
            {"value": provider, "label": LLMProvider.DISPLAY_NAMES.get(provider, provider)}
            for provider in LLMProvider.ALL
        ], 200


@workspace_llm_ns.route("/workspaces/<string:workspace_id>/llms")
class WorkspaceLLMList(ForgeResource):
    @token_required
    def get(self, workspace_id: str):
        try:
            svc = WorkspaceLLMService()
            return svc.get_all_for_workspace(workspace_id), 200
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 400)
        except Exception:
            logger.exception("GET workspace llms failed ws=%s", workspace_id)
            return {"error": "Failed to list workspace LLMs"}, 500

    @workspace_llm_ns.expect(_llm_create_model)
    @token_required
    def post(self, workspace_id: str):
        body = request.get_json(silent=True) or {}
        try:
            svc = WorkspaceLLMService()
            result = svc.create_llm(workspace_id, body)
            return result, 201
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 400)
        except Exception:
            logger.exception("POST workspace llm failed ws=%s", workspace_id)
            return {"error": "Failed to create workspace LLM"}, 500


@workspace_llm_ns.route("/workspaces/<string:workspace_id>/llms/<int:llm_id>")
class WorkspaceLLMDetail(ForgeResource):
    @token_required
    def get(self, workspace_id: str, llm_id: int):
        try:
            svc = WorkspaceLLMService()
            result = svc.get_by_id(llm_id)
            if result is None or result.get("workspace_id") != workspace_id:
                return {"error": "Not found"}, 404
            return result, 200
        except Exception:
            logger.exception("GET workspace llm detail failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Failed to get workspace LLM"}, 500

    @token_required
    def put(self, workspace_id: str, llm_id: int):
        body = request.get_json(silent=True) or {}
        try:
            svc = WorkspaceLLMService()
            result = svc.update_llm(llm_id, body)
            return result, 200
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception:
            logger.exception("PUT workspace llm failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Failed to update workspace LLM"}, 500

    @token_required
    def delete(self, workspace_id: str, llm_id: int):
        try:
            svc = WorkspaceLLMService()
            svc.delete_llm(llm_id)
            return {"deleted": True}, 200
        except Exception:
            logger.exception("DELETE workspace llm failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Failed to delete workspace LLM"}, 500


@workspace_llm_ns.route("/workspaces/<string:workspace_id>/llms/<int:llm_id>/test")
class WorkspaceLLMTest(ForgeResource):
    @token_required
    def post(self, workspace_id: str, llm_id: int):
        try:
            svc = WorkspaceLLMService()
            result = svc.test_connection(llm_id)
            return result, 200
        except Exception:
            logger.exception("POST workspace llm test failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Connection test failed"}, 500
```

**Step 4: Register namespaces in factory.py**

In `query-forge-api/app/factory.py`, add the following imports (near other route imports):

```python
from app.routes.workspace_llm_routes import workspace_llm_ns, _llm_roles_ns, _llm_providers_ns
```

Then find where `api.add_namespace(...)` calls are made and add:

```python
api.add_namespace(_llm_roles_ns, path="/llm-roles")
api.add_namespace(_llm_providers_ns, path="/llm-providers")
api.add_namespace(workspace_llm_ns, path="/")
```

**Step 5: Run route tests**

```bash
pytest tests/routes/test_workspace_llm_routes.py -v
```
Expected: PASS

**Step 6: Commit**

```bash
git add query-forge-api/app/routes/workspace_llm_routes.py \
        query-forge-api/app/factory.py \
        query-forge-api/tests/routes/test_workspace_llm_routes.py
git commit -m "feat: add workspace LLM CRUD and metadata routes"
```

---

## Task 7: Frontend — Types and API Client

**Files:**
- Modify: `query-forge-ui/src/features/system-admin/types/index.ts`
- Create: `query-forge-ui/src/features/system-admin/api/workspaceLLMApi.ts`

**Step 1: Add types to index.ts**

In `query-forge-ui/src/features/system-admin/types/index.ts`, add:

```typescript
// ── Workspace LLM ─────────────────────────────────────────────────────────

export type LLMRole = "planner" | "ner" | "summarizer" | "query_generator" | "enrichment";

export type LLMProvider = "openai" | "anthropic" | "azure_openai" | "ollama" | "generic";

export interface WorkspaceLLM {
  id: number;
  workspace_id: string;
  name: string;
  provider: LLMProvider;
  model_name: string;
  role: LLMRole;
  has_api_key: boolean;
  masked_api_key: string | null;
  endpoint_url: string | null;
  is_active: boolean;
  config_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceLLMCreateRequest {
  name: string;
  provider: LLMProvider;
  model_name: string;
  role: LLMRole;
  api_key?: string;
  endpoint_url?: string | null;
  is_active?: boolean;
  config_json?: Record<string, unknown> | null;
}

export interface WorkspaceLLMUpdateRequest extends Partial<WorkspaceLLMCreateRequest> {}

export interface LLMRoleOption {
  value: LLMRole;
  label: string;
}

export interface LLMProviderOption {
  value: LLMProvider;
  label: string;
}

export interface LLMTestResult {
  success: boolean;
  message: string;
}
```

**Step 2: Create the API client**

`query-forge-ui/src/features/system-admin/api/workspaceLLMApi.ts`:
```typescript
import api from "@/shared/services/api";
import type {
  LLMProviderOption,
  LLMRoleOption,
  LLMTestResult,
  WorkspaceLLM,
  WorkspaceLLMCreateRequest,
  WorkspaceLLMUpdateRequest,
} from "../types";

export async function listLLMRoles(): Promise<LLMRoleOption[]> {
  const resp = await api.get<LLMRoleOption[]>("/llm-roles");
  return resp.data;
}

export async function listLLMProviders(): Promise<LLMProviderOption[]> {
  const resp = await api.get<LLMProviderOption[]>("/llm-providers");
  return resp.data;
}

export async function listWorkspaceLLMs(workspaceId: string): Promise<WorkspaceLLM[]> {
  const resp = await api.get<WorkspaceLLM[]>(`/workspaces/${workspaceId}/llms`);
  return resp.data;
}

export async function createWorkspaceLLM(
  workspaceId: string,
  payload: WorkspaceLLMCreateRequest
): Promise<WorkspaceLLM> {
  const resp = await api.post<WorkspaceLLM>(`/workspaces/${workspaceId}/llms`, payload);
  return resp.data;
}

export async function updateWorkspaceLLM(
  workspaceId: string,
  llmId: number,
  payload: WorkspaceLLMUpdateRequest
): Promise<WorkspaceLLM> {
  const resp = await api.put<WorkspaceLLM>(`/workspaces/${workspaceId}/llms/${llmId}`, payload);
  return resp.data;
}

export async function deleteWorkspaceLLM(workspaceId: string, llmId: number): Promise<void> {
  await api.delete(`/workspaces/${workspaceId}/llms/${llmId}`);
}

export async function testWorkspaceLLM(workspaceId: string, llmId: number): Promise<LLMTestResult> {
  const resp = await api.post<LLMTestResult>(`/workspaces/${workspaceId}/llms/${llmId}/test`);
  return resp.data;
}
```

**Step 3: Export from api/index.ts**

In `query-forge-ui/src/features/system-admin/api/index.ts`, add:
```typescript
export * from "./workspaceLLMApi";
```

**Step 4: Commit**

```bash
git add query-forge-ui/src/features/system-admin/types/index.ts \
        query-forge-ui/src/features/system-admin/api/workspaceLLMApi.ts \
        query-forge-ui/src/features/system-admin/api/index.ts
git commit -m "feat: add WorkspaceLLM types and API client"
```

---

## Task 8: Frontend — React Query Hooks

**Files:**
- Create: `query-forge-ui/src/features/system-admin/hooks/useWorkspaceLLM.ts`
- Modify: `query-forge-ui/src/features/system-admin/hooks/index.ts`

**Step 1: Write the hooks**

`query-forge-ui/src/features/system-admin/hooks/useWorkspaceLLM.ts`:
```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createWorkspaceLLM,
  deleteWorkspaceLLM,
  listLLMProviders,
  listLLMRoles,
  listWorkspaceLLMs,
  testWorkspaceLLM,
  updateWorkspaceLLM,
} from "../api/workspaceLLMApi";
import type { WorkspaceLLMCreateRequest, WorkspaceLLMUpdateRequest } from "../types";

const llmKeys = {
  roles: ["llm-roles"] as const,
  providers: ["llm-providers"] as const,
  workspace: (workspaceId: string | null) => ["workspace-llms", workspaceId] as const,
};

export function useLLMRoles() {
  return useQuery({
    queryKey: llmKeys.roles,
    queryFn: listLLMRoles,
    staleTime: 5 * 60 * 1000, // roles don't change
  });
}

export function useLLMProviders() {
  return useQuery({
    queryKey: llmKeys.providers,
    queryFn: listLLMProviders,
    staleTime: 5 * 60 * 1000,
  });
}

export function useWorkspaceLLMs(workspaceId: string | null) {
  return useQuery({
    queryKey: llmKeys.workspace(workspaceId),
    queryFn: () => listWorkspaceLLMs(workspaceId!),
    enabled: Boolean(workspaceId),
  });
}

export function useCreateWorkspaceLLM(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: WorkspaceLLMCreateRequest) =>
      createWorkspaceLLM(workspaceId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: llmKeys.workspace(workspaceId) });
    },
  });
}

export function useUpdateWorkspaceLLM(workspaceId: string, llmId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: WorkspaceLLMUpdateRequest) =>
      updateWorkspaceLLM(workspaceId, llmId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: llmKeys.workspace(workspaceId) });
    },
  });
}

export function useDeleteWorkspaceLLM(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (llmId: number) => deleteWorkspaceLLM(workspaceId, llmId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: llmKeys.workspace(workspaceId) });
    },
  });
}

export function useTestWorkspaceLLM(workspaceId: string) {
  return useMutation({
    mutationFn: (llmId: number) => testWorkspaceLLM(workspaceId, llmId),
  });
}
```

**Step 2: Export from hooks/index.ts**

In `query-forge-ui/src/features/system-admin/hooks/index.ts`, add:
```typescript
export * from "./useWorkspaceLLM";
```

**Step 3: Commit**

```bash
git add query-forge-ui/src/features/system-admin/hooks/useWorkspaceLLM.ts \
        query-forge-ui/src/features/system-admin/hooks/index.ts
git commit -m "feat: add useWorkspaceLLM React Query hooks"
```

---

## Task 9: Frontend — Standalone LLM Management Page

**Files:**
- Create: `query-forge-ui/src/features/system-admin/ui/tenancy/WorkspaceLLMPage.tsx`
- Create: `query-forge-ui/src/features/system-admin/ui/tenancy/WorkspaceLLMPage.test.tsx`
- Modify: `query-forge-ui/src/app/navigation/routes.ts`
- Modify: `query-forge-ui/src/app/navigation/AppRoutes.tsx`

**Step 1: Add route constant**

In `routes.ts`, add inside the `routes` object:
```typescript
AdminTenancyWorkspaceLLMs: "/admin/tenancy/workspace-llms",
```

**Step 2: Write the page component**

`query-forge-ui/src/features/system-admin/ui/tenancy/WorkspaceLLMPage.tsx`:

```tsx
import { useState } from "react";
import { toast } from "react-toastify";
import {
  useLLMProviders,
  useLLMRoles,
  useWorkspaceLLMs,
  useCreateWorkspaceLLM,
  useUpdateWorkspaceLLM,
  useDeleteWorkspaceLLM,
  useTestWorkspaceLLM,
} from "@/features/system-admin/hooks";
import type {
  WorkspaceLLM,
  WorkspaceLLMCreateRequest,
  LLMProvider,
  LLMRole,
} from "@/features/system-admin/types";
import "../systemAdmin.css";

const ENDPOINT_PROVIDERS: LLMProvider[] = ["azure_openai", "ollama", "generic"];

type FormState = {
  name: string;
  provider: LLMProvider;
  model_name: string;
  role: LLMRole;
  api_key: string;
  endpoint_url: string;
  is_active: boolean;
  config_json_text: string;
};

function createEmptyForm(): FormState {
  return {
    name: "",
    provider: "openai",
    model_name: "",
    role: "planner",
    api_key: "",
    endpoint_url: "",
    is_active: true,
    config_json_text: "",
  };
}

function formToPayload(form: FormState): WorkspaceLLMCreateRequest {
  let config_json: Record<string, unknown> | null = null;
  if (form.config_json_text.trim()) {
    try {
      config_json = JSON.parse(form.config_json_text);
    } catch {
      config_json = null;
    }
  }
  return {
    name: form.name.trim(),
    provider: form.provider,
    model_name: form.model_name.trim(),
    role: form.role,
    api_key: form.api_key.trim() || undefined,
    endpoint_url: form.endpoint_url.trim() || null,
    is_active: form.is_active,
    config_json,
  };
}

export default function WorkspaceLLMPage() {
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("");
  const [showForm, setShowForm] = useState(false);
  const [editingLLM, setEditingLLM] = useState<WorkspaceLLM | null>(null);
  const [form, setForm] = useState<FormState>(createEmptyForm);
  const [testResult, setTestResult] = useState<{ id: number; success: boolean; message: string } | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);

  const wsId = selectedWorkspaceId.trim() || null;

  const rolesQuery = useLLMRoles();
  const providersQuery = useLLMProviders();
  const llmsQuery = useWorkspaceLLMs(wsId);
  const createMutation = useCreateWorkspaceLLM(wsId ?? "");
  const deleteMutation = useDeleteWorkspaceLLM(wsId ?? "");
  const testMutation = useTestWorkspaceLLM(wsId ?? "");

  const openAdd = () => {
    setEditingLLM(null);
    setForm(createEmptyForm());
    setTestResult(null);
    setShowForm(true);
  };

  const openEdit = (llm: WorkspaceLLM) => {
    setEditingLLM(llm);
    setForm({
      name: llm.name,
      provider: llm.provider,
      model_name: llm.model_name,
      role: llm.role,
      api_key: "",
      endpoint_url: llm.endpoint_url ?? "",
      is_active: llm.is_active,
      config_json_text: llm.config_json ? JSON.stringify(llm.config_json, null, 2) : "",
    });
    setTestResult(null);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!wsId) return;
    const payload = formToPayload(form);
    try {
      if (editingLLM) {
        const updateMutation = useUpdateWorkspaceLLM(wsId, editingLLM.id);
        await updateMutation.mutateAsync(payload);
        toast.success("LLM configuration updated.");
      } else {
        await createMutation.mutateAsync(payload);
        toast.success("LLM configuration created.");
      }
      setShowForm(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save LLM configuration.";
      toast.error(msg);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteMutation.mutateAsync(id);
      setDeleteConfirmId(null);
      toast.success("LLM configuration deleted.");
    } catch {
      toast.error("Failed to delete LLM configuration.");
    }
  };

  const handleTest = async (llm: WorkspaceLLM) => {
    if (!wsId) return;
    setTestResult(null);
    try {
      const result = await testMutation.mutateAsync(llm.id);
      setTestResult({ id: llm.id, ...result });
    } catch {
      setTestResult({ id: llm.id, success: false, message: "Connection test failed." });
    }
  };

  const needsEndpoint = ENDPOINT_PROVIDERS.includes(form.provider);

  return (
    <div className="sa-page">
      <div className="sa-page-header">
        <div>
          <h1>Workspace LLM Configuration</h1>
          <p className="sa-page-subtitle">
            Assign LLM models to pipeline roles for each workspace.
          </p>
        </div>
      </div>

      {/* Workspace selector */}
      <div className="sa-card mb-3">
        <label htmlFor="ws-selector" className="sa-card-title mb-2 d-block">
          Select Workspace
        </label>
        <input
          id="ws-selector"
          className="form-control"
          style={{ maxWidth: 400 }}
          placeholder="Enter workspace ID"
          value={selectedWorkspaceId}
          onChange={(e) => setSelectedWorkspaceId(e.target.value)}
          aria-label="Workspace ID"
        />
      </div>

      {wsId && (
        <>
          {/* LLM table */}
          <div className="sa-card mb-3">
            <div className="d-flex justify-content-between align-items-center mb-3">
              <div className="sa-card-title mb-0">LLM Configurations</div>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={openAdd}
                aria-label="Add LLM configuration"
              >
                + Add LLM
              </button>
            </div>

            {llmsQuery.isLoading && <div className="text-muted">Loading...</div>}
            {llmsQuery.isError && (
              <div className="alert alert-danger" role="alert">
                Failed to load LLM configurations.
              </div>
            )}

            {llmsQuery.data && llmsQuery.data.length === 0 && (
              <div className="text-muted py-3 text-center">
                No LLM configurations for this workspace. Click + Add LLM to get started.
              </div>
            )}

            {llmsQuery.data && llmsQuery.data.length > 0 && (
              <div className="table-responsive">
                <table className="table table-hover align-middle" aria-label="LLM configurations">
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Role</th>
                      <th scope="col">Provider</th>
                      <th scope="col">Model</th>
                      <th scope="col">API Key</th>
                      <th scope="col">Status</th>
                      <th scope="col">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {llmsQuery.data.map((llm) => (
                      <tr key={llm.id}>
                        <td>{llm.name}</td>
                        <td>
                          <span className="badge bg-secondary">{llm.role}</span>
                        </td>
                        <td>{llm.provider}</td>
                        <td>
                          <code>{llm.model_name}</code>
                        </td>
                        <td>
                          {llm.has_api_key ? (
                            <span className="text-muted" aria-label="API key configured">
                              {llm.masked_api_key ?? "••••"}
                            </span>
                          ) : (
                            <span className="text-muted" aria-label="No API key">—</span>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${llm.is_active ? "bg-success" : "bg-secondary"}`}>
                            {llm.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td>
                          <div className="d-flex gap-1">
                            <button
                              type="button"
                              className="btn btn-outline-secondary btn-sm"
                              onClick={() => openEdit(llm)}
                              aria-label={`Edit ${llm.name}`}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="btn btn-outline-primary btn-sm"
                              onClick={() => handleTest(llm)}
                              disabled={testMutation.isPending}
                              aria-label={`Test connection for ${llm.name}`}
                            >
                              Test
                            </button>
                            <button
                              type="button"
                              className="btn btn-outline-danger btn-sm"
                              onClick={() => setDeleteConfirmId(llm.id)}
                              aria-label={`Delete ${llm.name}`}
                            >
                              Delete
                            </button>
                          </div>
                          {testResult?.id === llm.id && (
                            <div
                              className={`mt-1 small ${testResult.success ? "text-success" : "text-danger"}`}
                              role="status"
                              aria-live="polite"
                            >
                              {testResult.success ? "✓" : "✗"} {testResult.message}
                            </div>
                          )}
                          {deleteConfirmId === llm.id && (
                            <div className="mt-1 d-flex gap-1 align-items-center">
                              <span className="small text-danger">Confirm delete?</span>
                              <button
                                type="button"
                                className="btn btn-danger btn-sm"
                                onClick={() => void handleDelete(llm.id)}
                                disabled={deleteMutation.isPending}
                              >
                                Yes
                              </button>
                              <button
                                type="button"
                                className="btn btn-light btn-sm"
                                onClick={() => setDeleteConfirmId(null)}
                              >
                                No
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Add/Edit form */}
          {showForm && (
            <div className="sa-card mb-3" role="region" aria-label={editingLLM ? "Edit LLM" : "Add LLM"}>
              <div className="sa-card-title">{editingLLM ? `Edit: ${editingLLM.name}` : "Add LLM Configuration"}</div>
              <div className="row g-3 mt-1">
                <div className="col-md-6">
                  <label htmlFor="llm-name" className="form-label">
                    Name *
                  </label>
                  <input
                    id="llm-name"
                    className="form-control"
                    value={form.name}
                    onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                    required
                  />
                </div>

                <div className="col-md-3">
                  <label htmlFor="llm-provider" className="form-label">
                    Provider *
                  </label>
                  <select
                    id="llm-provider"
                    className="form-select"
                    value={form.provider}
                    onChange={(e) => setForm((p) => ({ ...p, provider: e.target.value as LLMProvider }))}
                  >
                    {(providersQuery.data ?? []).map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="col-md-3">
                  <label htmlFor="llm-role" className="form-label">
                    Role *
                  </label>
                  <select
                    id="llm-role"
                    className="form-select"
                    value={form.role}
                    onChange={(e) => setForm((p) => ({ ...p, role: e.target.value as LLMRole }))}
                  >
                    {(rolesQuery.data ?? []).map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="col-md-6">
                  <label htmlFor="llm-model" className="form-label">
                    Model Name *
                  </label>
                  <input
                    id="llm-model"
                    className="form-control"
                    value={form.model_name}
                    onChange={(e) => setForm((p) => ({ ...p, model_name: e.target.value }))}
                    placeholder="e.g. gpt-4o, claude-sonnet-4-6, llama3"
                    required
                  />
                </div>

                <div className="col-md-6">
                  <label htmlFor="llm-api-key" className="form-label">
                    API Key {editingLLM ? "(leave blank to keep existing)" : ""}
                  </label>
                  <input
                    id="llm-api-key"
                    type="password"
                    className="form-control"
                    value={form.api_key}
                    onChange={(e) => setForm((p) => ({ ...p, api_key: e.target.value }))}
                    autoComplete="off"
                    aria-describedby="api-key-hint"
                  />
                  <div id="api-key-hint" className="form-text">
                    {editingLLM?.has_api_key
                      ? `Currently set: ${editingLLM.masked_api_key ?? "••••"}. Enter new key to replace.`
                      : "API key is encrypted at rest."}
                  </div>
                </div>

                {needsEndpoint && (
                  <div className="col-12">
                    <label htmlFor="llm-endpoint" className="form-label">
                      Endpoint URL {needsEndpoint ? "*" : ""}
                    </label>
                    <input
                      id="llm-endpoint"
                      className="form-control"
                      value={form.endpoint_url}
                      onChange={(e) => setForm((p) => ({ ...p, endpoint_url: e.target.value }))}
                      placeholder="https://your-resource.openai.azure.com"
                      aria-required={needsEndpoint}
                    />
                  </div>
                )}

                <div className="col-12">
                  <div className="form-check">
                    <input
                      id="llm-active"
                      type="checkbox"
                      className="form-check-input"
                      checked={form.is_active}
                      onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.checked }))}
                    />
                    <label htmlFor="llm-active" className="form-check-label">
                      Active
                    </label>
                  </div>
                </div>

                <div className="col-12">
                  <details>
                    <summary className="text-muted small" style={{ cursor: "pointer" }}>
                      Advanced config (optional JSON)
                    </summary>
                    <div className="mt-2">
                      <label htmlFor="llm-config" className="form-label">
                        config_json
                      </label>
                      <textarea
                        id="llm-config"
                        className="form-control font-monospace"
                        rows={4}
                        value={form.config_json_text}
                        onChange={(e) => setForm((p) => ({ ...p, config_json_text: e.target.value }))}
                        aria-label="Optional JSON configuration"
                      />
                    </div>
                  </details>
                </div>
              </div>

              <div className="mt-3 d-flex gap-2 justify-content-end">
                <button
                  type="button"
                  className="btn btn-light"
                  onClick={() => setShowForm(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => void handleSave()}
                  disabled={createMutation.isPending || !form.name.trim() || !form.model_name.trim()}
                >
                  {createMutation.isPending ? "Saving..." : editingLLM ? "Update" : "Create"}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

**IMPORTANT NOTE:** The `useUpdateWorkspaceLLM` hook is called inside `handleSave`. Since hooks cannot be called conditionally, refactor by accepting `editingLLM` in the mutation. Use `useUpdateWorkspaceLLM` at the top level with a sentinel llmId and only call `mutateAsync` when editing. The simplest fix is to use the raw API function directly for updates in the save handler:

```tsx
// Replace handleSave to use direct API call for updates:
import { updateWorkspaceLLM } from "@/features/system-admin/api";
import { useQueryClient } from "@tanstack/react-query";

// Inside the component, get queryClient:
const queryClient = useQueryClient();

const handleSave = async () => {
  if (!wsId) return;
  const payload = formToPayload(form);
  try {
    if (editingLLM) {
      await updateWorkspaceLLM(wsId, editingLLM.id, payload);
      void queryClient.invalidateQueries({ queryKey: ["workspace-llms", wsId] });
      toast.success("LLM configuration updated.");
    } else {
      await createMutation.mutateAsync(payload);
      toast.success("LLM configuration created.");
    }
    setShowForm(false);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Failed to save.";
    toast.error(msg);
  }
};
```

**Step 3: Register in AppRoutes.tsx**

Add to imports:
```tsx
import WorkspaceLLMPage from "../../features/system-admin/ui/tenancy/WorkspaceLLMPage";
```

Add to the `appRuntimeConfig.adminTenancyEnabled` block:
```tsx
{
  path: routes.AdminTenancyWorkspaceLLMs,
  element: <WorkspaceLLMPage />,
  access: { kind: "admin" } as const,
},
```

**Step 4: Write the component test**

`query-forge-ui/src/features/system-admin/ui/tenancy/WorkspaceLLMPage.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { beforeAll, afterAll, afterEach, describe, it, expect } from "vitest";
import WorkspaceLLMPage from "./WorkspaceLLMPage";

const server = setupServer(
  http.get("*/llm-roles", () =>
    HttpResponse.json([
      { value: "planner", label: "Planner" },
      { value: "ner", label: "Named Entity Recognition" },
    ])
  ),
  http.get("*/llm-providers", () =>
    HttpResponse.json([
      { value: "openai", label: "OpenAI" },
      { value: "anthropic", label: "Anthropic" },
    ])
  ),
  http.get("*/workspaces/ws1/llms", () =>
    HttpResponse.json([
      {
        id: 1,
        workspace_id: "ws1",
        name: "GPT-4 Planner",
        provider: "openai",
        model_name: "gpt-4o",
        role: "planner",
        has_api_key: true,
        masked_api_key: "sk-1234...****",
        endpoint_url: null,
        is_active: true,
        config_json: null,
        created_at: "",
        updated_at: "",
      },
    ])
  )
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrapper(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("WorkspaceLLMPage", () => {
  it("renders page heading", () => {
    render(wrapper(<WorkspaceLLMPage />));
    expect(screen.getByText("Workspace LLM Configuration")).toBeInTheDocument();
  });

  it("shows workspace selector", () => {
    render(wrapper(<WorkspaceLLMPage />));
    expect(screen.getByLabelText("Workspace ID")).toBeInTheDocument();
  });

  it("shows Add LLM button when workspace is entered", async () => {
    const { getByLabelText, findByText } = render(wrapper(<WorkspaceLLMPage />));
    const input = getByLabelText("Workspace ID");
    await import("@testing-library/user-event").then(async ({ default: userEvent }) => {
      await userEvent.type(input, "ws1");
    });
    expect(await findByText("+ Add LLM")).toBeInTheDocument();
  });
});
```

**Step 5: Run the frontend test**

```bash
cd query-forge-ui
npm run test:coverage -- --testPathPattern="WorkspaceLLMPage"
```
Expected: PASS for the 3 basic tests.

**Step 6: Commit**

```bash
git add query-forge-ui/src/features/system-admin/ui/tenancy/WorkspaceLLMPage.tsx \
        query-forge-ui/src/features/system-admin/ui/tenancy/WorkspaceLLMPage.test.tsx \
        query-forge-ui/src/app/navigation/routes.ts \
        query-forge-ui/src/app/navigation/AppRoutes.tsx
git commit -m "feat: add WorkspaceLLM management page with full CRUD and test connection"
```

---

## Task 10: Frontend — Customer Initialization Step 4

**Files:**
- Modify: `query-forge-ui/src/features/system-admin/ui/tenancy/CustomerInitializationPage.tsx`

**Context:** Current wizard has 4 steps; Step 4 is "Bind + Confirm". We insert new Step 4 = "Configure LLMs" (skippable) and rename old Step 4 to Step 5. The `WizardStep` type changes from `1|2|3|4` to `1|2|3|4|5`.

**Step 1: Make changes to CustomerInitializationPage.tsx**

Key changes (find these in the file and make targeted edits):

1. **Change the type:** `type WizardStep = 1 | 2 | 3 | 4;` → `type WizardStep = 1 | 2 | 3 | 4 | 5;`

2. **Add LLM form types:**
```tsx
type LLMDraftRow = {
  id: string; // local UUID for list key
  name: string;
  provider: string;
  model_name: string;
  role: string;
  api_key: string;
  endpoint_url: string;
  is_active: boolean;
};

function createLLMDraftRow(): LLMDraftRow {
  return {
    id: crypto.randomUUID(),
    name: "",
    provider: "openai",
    model_name: "",
    role: "planner",
    api_key: "",
    endpoint_url: "",
    is_active: true,
  };
}
```

3. **Add state inside the component:**
```tsx
const [llmDrafts, setLlmDrafts] = useState<LLMDraftRow[]>([]);
const [llmSaveErrors, setLlmSaveErrors] = useState<string[]>([]);
const [llmsSaved, setLlmsSaved] = useState(false);
```

4. **Update the wizard steps array** — change old Step 4 from label "Bind + Confirm" with step `4` to step `5`, and add new step 4:
```tsx
{ step: 4 as const, label: "LLMs (Optional)", detail: llmsSaved ? `${llmDrafts.length} configured` : "Configure LLMs for workspace" },
{ step: 5 as const, label: "Bind + Confirm", detail: binding ? "Workspace bound" : "Attach datasource" },
```

5. **Fix `getStepStatus`:** Change `step < 4` and `step === 4` to `step < 5` and `step === 5`.

6. **Update all `setActiveStep(4)` calls** (after datasource creation) to `setActiveStep(4)`.

7. **Update `handleBindWorkspace`** to call `setActiveStep(5)` when navigating back. Fix the `activeStep === 4` condition to now be `activeStep === 5`.

8. **Add handler for Step 4 LLMs:**
```tsx
const handleSaveLLMs = async () => {
  if (!workspaceId) {
    setActiveStep(5);
    return;
  }
  const errors: string[] = [];
  for (const draft of llmDrafts) {
    if (!draft.name.trim() || !draft.model_name.trim()) continue;
    try {
      await createWorkspaceLLM(workspaceId, {
        name: draft.name.trim(),
        provider: draft.provider as LLMProvider,
        model_name: draft.model_name.trim(),
        role: draft.role as LLMRole,
        api_key: draft.api_key.trim() || undefined,
        endpoint_url: draft.endpoint_url.trim() || null,
        is_active: draft.is_active,
      });
    } catch (err) {
      errors.push(`${draft.name}: ${err instanceof Error ? err.message : "Failed"}`);
    }
  }
  setLlmSaveErrors(errors);
  if (errors.length === 0) {
    setLlmsSaved(true);
    setActiveStep(5);
  }
};
```

Add import at top: `import { createWorkspaceLLM } from "@/features/system-admin/api";`

9. **Add Step 4 JSX** (between the existing Step 3 and Step 4 blocks):
```tsx
{activeStep === 4 && (
  <div className="sa-card mb-3">
    <div className="sa-card-title">Step 4: Configure LLMs (Optional)</div>
    <p className="sa-page-subtitle">
      Assign LLM models to pipeline roles for workspace <strong>{workspaceId ?? "-"}</strong>.
      You can skip this step and configure LLMs later from System Admin → Tenancy → Workspace LLMs.
    </p>

    {llmDrafts.map((draft, idx) => (
      <div key={draft.id} className="border rounded p-3 mb-3">
        <div className="d-flex justify-content-between mb-2">
          <strong>LLM {idx + 1}</strong>
          <button
            type="button"
            className="btn btn-sm btn-outline-danger"
            onClick={() => setLlmDrafts((prev) => prev.filter((r) => r.id !== draft.id))}
            aria-label={`Remove LLM ${idx + 1}`}
          >
            Remove
          </button>
        </div>
        <div className="row g-2">
          <div className="col-md-4">
            <label htmlFor={`llm-name-${draft.id}`} className="form-label">Name</label>
            <input
              id={`llm-name-${draft.id}`}
              className="form-control form-control-sm"
              value={draft.name}
              onChange={(e) =>
                setLlmDrafts((prev) =>
                  prev.map((r) => (r.id === draft.id ? { ...r, name: e.target.value } : r))
                )
              }
            />
          </div>
          <div className="col-md-3">
            <label htmlFor={`llm-provider-${draft.id}`} className="form-label">Provider</label>
            <select
              id={`llm-provider-${draft.id}`}
              className="form-select form-select-sm"
              value={draft.provider}
              onChange={(e) =>
                setLlmDrafts((prev) =>
                  prev.map((r) => (r.id === draft.id ? { ...r, provider: e.target.value } : r))
                )
              }
            >
              {["openai", "anthropic", "azure_openai", "ollama", "generic"].map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="col-md-3">
            <label htmlFor={`llm-role-${draft.id}`} className="form-label">Role</label>
            <select
              id={`llm-role-${draft.id}`}
              className="form-select form-select-sm"
              value={draft.role}
              onChange={(e) =>
                setLlmDrafts((prev) =>
                  prev.map((r) => (r.id === draft.id ? { ...r, role: e.target.value } : r))
                )
              }
            >
              {["planner", "ner", "summarizer", "query_generator", "enrichment"].map((role) => (
                <option key={role} value={role}>{role}</option>
              ))}
            </select>
          </div>
          <div className="col-md-4">
            <label htmlFor={`llm-model-${draft.id}`} className="form-label">Model Name</label>
            <input
              id={`llm-model-${draft.id}`}
              className="form-control form-control-sm"
              value={draft.model_name}
              onChange={(e) =>
                setLlmDrafts((prev) =>
                  prev.map((r) => (r.id === draft.id ? { ...r, model_name: e.target.value } : r))
                )
              }
              placeholder="e.g. gpt-4o"
            />
          </div>
          <div className="col-md-4">
            <label htmlFor={`llm-key-${draft.id}`} className="form-label">API Key</label>
            <input
              id={`llm-key-${draft.id}`}
              type="password"
              className="form-control form-control-sm"
              value={draft.api_key}
              onChange={(e) =>
                setLlmDrafts((prev) =>
                  prev.map((r) => (r.id === draft.id ? { ...r, api_key: e.target.value } : r))
                )
              }
              autoComplete="off"
              aria-label="API key (masked)"
            />
          </div>
          {["azure_openai", "ollama", "generic"].includes(draft.provider) && (
            <div className="col-md-6">
              <label htmlFor={`llm-endpoint-${draft.id}`} className="form-label">Endpoint URL</label>
              <input
                id={`llm-endpoint-${draft.id}`}
                className="form-control form-control-sm"
                value={draft.endpoint_url}
                onChange={(e) =>
                  setLlmDrafts((prev) =>
                    prev.map((r) => (r.id === draft.id ? { ...r, endpoint_url: e.target.value } : r))
                  )
                }
                placeholder="https://..."
              />
            </div>
          )}
        </div>
      </div>
    ))}

    {llmSaveErrors.length > 0 && (
      <div className="alert alert-warning" role="alert">
        Some LLMs failed to save:
        <ul className="mb-0 mt-1">
          {llmSaveErrors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      </div>
    )}

    <button
      type="button"
      className="btn btn-outline-secondary btn-sm mb-3"
      onClick={() => setLlmDrafts((prev) => [...prev, createLLMDraftRow()])}
    >
      + Add LLM
    </button>

    <div className="mt-3 d-flex justify-content-between">
      <button type="button" className="btn btn-light" onClick={() => setActiveStep(3)}>
        Back
      </button>
      <div className="d-flex gap-2">
        <button type="button" className="btn btn-light" onClick={() => setActiveStep(5)}>
          Skip
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void handleSaveLLMs()}
          disabled={llmDrafts.length === 0}
        >
          Save LLMs &amp; Continue
        </button>
      </div>
    </div>
  </div>
)}
```

10. **Fix the existing Step 4 "Bind + Confirm" block** — change `activeStep === 4` to `activeStep === 5` and update the "Back" button to go to step 4.

11. **Update `resetWizard`** to reset `llmDrafts`, `llmSaveErrors`, `llmsSaved`.

**Step 2: Run the existing CustomerInitializationPage test to confirm nothing is broken**

```bash
cd query-forge-ui
npx vitest run src/features/system-admin/ui/tenancy/CustomerInitializationPage.test.tsx
```
Expected: PASS (the test file may need minor updates if it asserts step count — update it to expect 5 steps).

**Step 3: Commit**

```bash
git add query-forge-ui/src/features/system-admin/ui/tenancy/CustomerInitializationPage.tsx
git commit -m "feat: add Step 4 LLM configuration to customer initialization wizard"
```

---

## Task 11: ADA Accessibility Review

Run the ADA agent with this checklist and save findings.

**Checklist:**
- [ ] `WorkspaceLLMPage`: All form inputs have visible persistent `<label>` elements with `htmlFor`
- [ ] Provider/role `<select>` elements are keyboard navigable (native — should pass)
- [ ] API key `<input type="password">` has `autoComplete="off"` and `aria-label` or linked label
- [ ] Endpoint URL field uses `aria-required` when conditionally shown
- [ ] Test connection result uses `aria-live="polite"` role="status"
- [ ] Delete confirm inline row: focus returns correctly after confirmation
- [ ] Table has `<th scope="col">` headers
- [ ] CustomerInitializationPage Step 4: All draft LLM inputs have `htmlFor`/`id` pairs
- [ ] API key inputs in wizard have `autoComplete="off"` and `aria-label`
- [ ] Step skip button has clear label

Save findings to: `.claude/audits/ada-audit.md`

---

## Task 12: Save Implementation Notes

Save to `.claude/audits/implementation-notes.md`:

```markdown
# Workspace LLM Configuration — Implementation Notes

**Date:** 2026-03-11

## Tables Created

- `workspace_llm` — see `migrations/20260311_add_workspace_llm.sql`
  - workspace_id VARCHAR(255) (string FK, matches existing workspace identity)
  - api_key_encrypted TEXT nullable (Fernet-encrypted at rest)
  - role VARCHAR(64) (planner | ner | summarizer | query_generator | enrichment)
  - provider VARCHAR(64) (openai | anthropic | azure_openai | ollama | generic)
  - Unique constraint: enforced in service layer (MySQL partial index limitation)

## Routes Added

```
GET    /api/v1/llm-roles
GET    /api/v1/llm-providers
GET    /api/v1/workspaces/{workspace_id}/llms
POST   /api/v1/workspaces/{workspace_id}/llms
GET    /api/v1/workspaces/{workspace_id}/llms/{llm_id}
PUT    /api/v1/workspaces/{workspace_id}/llms/{llm_id}
DELETE /api/v1/workspaces/{workspace_id}/llms/{llm_id}
POST   /api/v1/workspaces/{workspace_id}/llms/{llm_id}/test
```

## Encryption Approach

Fernet symmetric encryption (cryptography library). Key from `QF_ENCRYPTION_KEY` env var.
- Raw API key never persisted; always encrypted via `encrypt_api_key()` before DB write
- Never returned in REST responses — only `has_api_key: bool` and `masked_api_key: str | null`
- Decryption happens only in `_to_internal_dict()` for internal pipeline use

## Fallback Behavior

`WorkspaceLLMService.get_llm_for_role()` falls back to env var config when no DB record exists:
- planner/query_generator/enrichment → `VLLM_BASE_URL` + `SEMANTIC_PLAN_LLM_MODEL`
- ner/summarizer → `SEMANTIC_LLM_ENDPOINT` + `SEMANTIC_LLM_MODEL`
- Returns `None` if neither DB nor env is configured

Pipeline integrates via `app.config.llm_resolver.resolve_llm_config(workspace_id, role)`.

## Unique Active LLM Per Role

MySQL partial unique indexes not used. Enforced in `WorkspaceLLMService._assert_no_active_for_role()`.
Service raises `ValueError` if creating/updating would create a second active LLM for same workspace+role.

## Frontend Surfaces

1. **CustomerInitializationPage** — Step 4 (new, optional) with multi-row LLM draft list. Step 5 = old "Bind + Confirm".
2. **WorkspaceLLMPage** — Standalone page at `/admin/tenancy/workspace-llms` under System Admin → Tenancy.

## Deferred Items

- Navigation sidebar link for WorkspaceLLMPage not added (sidebar uses static menuList — add if sidebar is updated)
- `test_connection` uses `httpx` — ensure it's in requirements.txt
- Full E2E Playwright tests deferred
```

---

## Final Verification

```bash
# Backend
cd query-forge-api
./scripts/lint.sh
pytest tests/test_llm_constants.py tests/test_encryption.py \
       tests/services/tenancy/test_workspace_llm_service.py \
       tests/config/test_llm_resolver.py \
       tests/routes/test_workspace_llm_routes.py -v

# Frontend
cd query-forge-ui
npm run test:coverage -- --testPathPattern="WorkspaceLLM|CustomerInitialization"
npm run build
```

All tests green, build passes → implementation complete.

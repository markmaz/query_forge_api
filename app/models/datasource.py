from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class Datasource(BaseModel):
    id: Optional[int] = None
    organization_id: str
    name: str
    slug: str
    type: str
    description: Optional[str] = None
    is_active: bool = True
    secret_ref: Optional[str] = None
    config_json: Optional[Dict[str, Any]] = None
    last_tested_at: Optional[datetime] = None
    last_test_status: Optional[str] = None
    last_test_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Organization(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

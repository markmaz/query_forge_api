from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OrganizationMembership(BaseModel):
    id: Optional[int] = None
    organization_id: str
    user_id: str
    role: str = "member"
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

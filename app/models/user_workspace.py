from typing import Optional

from pydantic import BaseModel


class UserWorkspace(BaseModel):
    workspace_id: Optional[str]
    is_default: Optional[bool]
from typing import Optional

from pydantic import BaseModel


class Workspace(BaseModel):
    workspace_id: Optional[str]
    is_default: Optional[bool]
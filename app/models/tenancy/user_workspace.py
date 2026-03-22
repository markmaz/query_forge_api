from typing import List, Optional

from pydantic import BaseModel, EmailStr


class UserWorkspace(BaseModel):
    workspace_id: Optional[str]
    is_default: Optional[bool]


class UserInvitation(BaseModel):
    email: EmailStr
    user_id: Optional[str] = None
    workspaces: Optional[List[UserWorkspace]] = []

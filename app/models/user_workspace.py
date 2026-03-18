from typing import List, Optional

from pydantic import BaseModel, EmailStr

from app.models.product import Product


class UserWorkspace(BaseModel):
    workspace_id: Optional[str]
    is_default: Optional[bool]


class UserInvitation(BaseModel):
    email: EmailStr
    user_id: Optional[str] = None
    products: Optional[List[Product]] = []
    workspaces: Optional[List[UserWorkspace]] = []
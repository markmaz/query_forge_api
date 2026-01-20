from typing import List, Optional

from pydantic import BaseModel, EmailStr

from app.models.product import Product
from app.models.user_workspace import Workspace


class UserInvitation(BaseModel):
    email: EmailStr
    user_id: Optional[str] = None
    products: Optional[List[Product]] = []
    workspaces: Optional[List[Workspace]] = []
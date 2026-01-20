
from pydantic import BaseModel

from app.models.role import Role


class ProductRole(BaseModel):
    role: Role
    product_role_id: str
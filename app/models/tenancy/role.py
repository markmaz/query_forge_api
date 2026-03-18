from pydantic import BaseModel


class Role(BaseModel):
    role_id: str
    role_name: str


class ProductRole(BaseModel):
    role: Role
    product_role_id: str
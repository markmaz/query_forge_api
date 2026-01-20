from pydantic import BaseModel


class Role(BaseModel):
    role_id: str
    role_name: str
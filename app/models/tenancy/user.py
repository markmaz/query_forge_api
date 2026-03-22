from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, computed_field, field_serializer

from app.models.tenancy.role import Role
from app.models.tenancy.user_workspace import UserWorkspace


class User(BaseModel):
    user_id: Optional[str] = None
    password: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    user_name: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = "New"
    tos_accepted: Optional[bool] = False
    eula_accepted: Optional[bool] = False
    otp_secret: Optional[str] = None
    two_factor_preference: Optional[str] = "Email"
    workspaces: Optional[List[UserWorkspace]] = []
    rbac_roles: Optional[List[Role]] = []
    rbac_role_names: Optional[List[str]] = []
    rbac_role_ids: Optional[List[str]] = []
    last_log_in: Optional[datetime] = None

    @computed_field
    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @field_serializer("last_log_in")
    def serialize_last_log_in(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value is not None else None
    
    model_config = ConfigDict(
        extra="ignore",
    )

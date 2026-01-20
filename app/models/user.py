from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.product import Product
from app.models.user_workspace import Workspace


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
    products: Optional[List[Product]] = []
    workspaces: Optional[List[Workspace]] = []
    last_log_in: Optional[datetime] = None

    @computed_field
    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
    
    model_config = ConfigDict(
        extra="ignore",
        json_encoders={datetime: lambda v: v.isoformat()},
    )

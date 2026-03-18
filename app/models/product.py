from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.product_role import ProductRole


class Product(BaseModel):
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    status: Optional[str] = None
    last_update: Optional[datetime] = None
    roles: List[ProductRole] = Field(default_factory=list)

    model_config = ConfigDict(
        extra="ignore",
        json_encoders = {
            datetime: lambda v: v.isoformat()
        },
    )

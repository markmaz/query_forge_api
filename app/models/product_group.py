from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.product import Product


class ProductGroup(BaseModel):
    product_group_id: str
    product_group_name: str
    status: str
    last_update: Optional[datetime] = None
    products: List[Product] = Field(default_factory=list)

    model_config = ConfigDict(
        extra="ignore",
        json_encoders = {
            datetime: lambda v: v.isoformat()
        },
    )

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.product import Product


class ProductGroup(BaseModel):
    product_group_id: str
    product_group_name: str
    status: str
    last_update: Optional[datetime] = None
    products: Optional[Product] = []

    model_config = ConfigDict(
        extra="ignore",
        json_encoders = {
            datetime: lambda v: v.isoformat()
        },
    )
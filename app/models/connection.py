from typing import Optional

from pydantic import BaseModel


class Connection(BaseModel):
        host: str
        path: str
        authentication: str
        name: str
        access_token: Optional[str] = None
        connection_id: Optional[str] = None
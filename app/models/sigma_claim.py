from typing import List, Optional

from pydantic import BaseModel


class SigmaClaim(BaseModel):
    sub: str
    iss: str
    jti: str
    iat: int
    exp: int
    account_type: Optional[str] = "embedUser"
    teams: Optional[List[str]] = None
    eval_connection_id: str
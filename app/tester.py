# from app.services.user_service import UserService

# user = UserService()

# user.create_user('admin', 'SEytp#$2^$S%bG3', 'api-admin@kytheralabs.com', first_name=None, last_name=None)

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    last_log_in: Optional[datetime] = None

u = User(last_log_in=datetime.now())
print(u.model_dump(mode="json"))

import os

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

load_dotenv()

URL_SUFFIX = os.getenv("URL_SUFFIX")
URL_PREFIX = os.getenv("URL_PREFIX")


class Workspace(BaseModel):
    workspace_id: str
    name: str
    server: str

    @field_validator("server", mode="before")
    def format_server_url(cls, value):
        if "https:" not in value:
            return f"{URL_PREFIX}{value}.{URL_SUFFIX}"
        return value
    
    @field_validator("workspace_id", mode="before")
    def convert_workspace_id_to_str(cls, value):
        return str(value)
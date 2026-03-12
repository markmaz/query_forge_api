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
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith(("https://", "http://")):
            return text
        if URL_PREFIX and URL_SUFFIX:
            return f"{URL_PREFIX}{text}.{URL_SUFFIX}"
        return text
    
    @field_validator("workspace_id", mode="before")
    def convert_workspace_id_to_str(cls, value):
        return str(value)

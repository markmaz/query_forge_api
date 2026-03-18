from pydantic import BaseModel, field_validator


class Workspace(BaseModel):
    workspace_id: str
    name: str
    server: str

    @field_validator("server", mode="before")
    def format_server_url(cls, value):
        return str(value or "").strip()
    
    @field_validator("workspace_id", mode="before")
    def convert_workspace_id_to_str(cls, value):
        return str(value)

from __future__ import annotations

import re
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = _SLUG_RE.sub("-", text)
    text = text.strip("-")
    return text


class OrganizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[str] = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    is_active: bool = True

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        v = value.strip()
        return v or None

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        v = normalize_slug(value)
        return v or None


class OrganizationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        v = normalize_slug(value)
        return v or None


class OrganizationMembershipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    role: str = Field(default="member", min_length=1, max_length=64)
    is_active: bool = True

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: Optional[str]) -> str:
        if value is None:
            return "member"
        text = str(value).strip()
        return text or "member"


class OrganizationMembershipUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Optional[str] = Field(default=None, min_length=1, max_length=64)
    is_active: Optional[bool] = None


DatasourceType = Literal["databricks", "snowflake", "mysql", "postgres", "bigquery"]


class DatasourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    type: DatasourceType
    description: Optional[str] = None
    is_active: bool = True
    secret_ref: Optional[str] = Field(default=None, max_length=512)
    config_json: Optional[Dict[str, Any]] = None

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, value: str) -> str:
        return str(value or "").strip().lower()

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        v = normalize_slug(value)
        return v or None


class DatasourceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    type: Optional[DatasourceType] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    secret_ref: Optional[str] = Field(default=None, max_length=512)
    config_json: Optional[Dict[str, Any]] = None

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return str(value or "").strip().lower()

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        v = normalize_slug(value)
        return v or None


class WorkspaceMembershipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    role: str = Field(default="member", min_length=1, max_length=64)
    is_active: bool = True
    is_default: bool = False

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: Optional[str]) -> str:
        if value is None:
            return "member"
        text = str(value).strip()
        return text or "member"


class WorkspaceMembershipUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Optional[str] = Field(default=None, min_length=1, max_length=64)
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class WorkspaceBindingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: Optional[str] = Field(default=None, max_length=128)
    datasource_id: Optional[int] = None
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    default_catalog: Optional[str] = Field(default=None, max_length=255)
    default_schema: Optional[str] = Field(default=None, max_length=255)


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: Optional[str] = Field(default=None, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    datasource_id: Optional[int] = None
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    is_active: bool = True
    default_catalog: Optional[str] = Field(default=None, max_length=255)
    default_schema: Optional[str] = Field(default=None, max_length=255)


class TenancyBootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1)
    organization_name: str = Field(min_length=1, max_length=255)
    organization_id: Optional[str] = Field(default=None, max_length=128)
    organization_slug: Optional[str] = Field(default=None, max_length=255)
    organization_description: Optional[str] = None

    datasource_name: str = Field(min_length=1, max_length=255)
    datasource_type: DatasourceType
    datasource_slug: Optional[str] = Field(default=None, max_length=255)
    datasource_description: Optional[str] = None
    datasource_secret_ref: Optional[str] = Field(default=None, max_length=512)
    datasource_config_json: Optional[Dict[str, Any]] = None

    default_catalog: Optional[str] = Field(default=None, max_length=255)
    default_schema: Optional[str] = Field(default=None, max_length=255)
    admin_user_id: Optional[str] = Field(default=None, max_length=255)

    @field_validator("datasource_type")
    @classmethod
    def _normalize_datasource_type(cls, value: str) -> str:
        return str(value or "").strip().lower()

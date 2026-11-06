from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaseCreate(BaseModel):
    """Fields accepted when creating a case in the configured demo tenant."""

    case_name: str = Field(min_length=1, max_length=200)
    case_description: str | None = Field(default=None, max_length=10000)
    jurisdiction: str | None = Field(default=None, max_length=100)
    court: str | None = Field(default=None, max_length=300)
    case_type: str | None = Field(default=None, max_length=100)

    @field_validator("case_name")
    @classmethod
    def case_name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("case_name must contain non-whitespace characters")
        return normalized


class CaseUpdate(BaseModel):
    """Fields accepted when updating/renaming a case."""

    case_name: str | None = Field(default=None, max_length=200)
    case_description: str | None = Field(default=None, max_length=10000)
    jurisdiction: str | None = Field(default=None, max_length=100)
    court: str | None = Field(default=None, max_length=300)
    case_type: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=50)

    @field_validator("case_name")
    @classmethod
    def case_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("case_name must contain non-whitespace characters")
        return normalized


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: UUID
    organization_id: UUID
    case_name: str
    case_description: str | None
    jurisdiction: str | None
    court: str | None
    case_type: str | None
    status: str
    created_at: datetime
    updated_at: datetime

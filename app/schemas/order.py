import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import validation as v


class ValidationIssue(BaseModel):
    field: str
    code: str
    message: str
    severity: Literal["error", "warning"]
    rejected_value: str | None = None


class OrderFields(BaseModel):
    """User-supplied order fields. Every value is optional; missing data stays null."""

    patient_first_name: str | None = Field(default=None, examples=["Marie"])
    patient_last_name: str | None = Field(default=None, examples=["Curie"])
    patient_dob: date | None = Field(default=None, examples=["1900-12-05"])
    provider_name: str | None = Field(default=None, examples=["Arjun Raj"])
    provider_npi: str | None = Field(default=None, examples=["1234567893"])
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("patient_first_name", "patient_last_name", "provider_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = v.normalize_whitespace(value)
        if error := v.check_person_name(value):
            raise ValueError(error)
        return value

    @field_validator("patient_dob")
    @classmethod
    def _dob(cls, value: date | None) -> date | None:
        if value is not None and (error := v.check_dob(value)):
            raise ValueError(error)
        return value

    @field_validator("provider_npi")
    @classmethod
    def _npi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = v.normalize_npi(value)
        if error := v.check_npi(value):
            raise ValueError(error)
        return value


class OrderCreate(OrderFields):
    pass


class OrderUpdate(OrderFields):
    """Partial update: only fields present in the request body are changed."""


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    patient_first_name: str | None
    patient_last_name: str | None
    patient_dob: date | None
    provider_name: str | None
    provider_npi: str | None
    notes: str | None
    validation_issues: list[ValidationIssue]
    source_filename: str | None
    source_sha256: str | None
    extraction: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class OrderList(BaseModel):
    items: list[OrderOut]
    total: int
    limit: int
    offset: int

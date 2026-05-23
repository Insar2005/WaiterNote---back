# backend/schemas/workplace.py
from typing import Optional
from pydantic import Field

from .common import APIModel, NanoID


# Snapshot of allowed shift types (mirror of models.ShiftTypeEnum)
ShiftType = str  # "fixed" | "percent" — validated via Literal below


class WorkplaceBase(APIModel):
    title: str = Field(min_length=1, max_length=255)
    timezone: str = Field(min_length=1, max_length=100)
    currency: str = Field(min_length=1, max_length=10)
    service_percent_default: int = Field(ge=0, le=100)
    shift_type_default: str = Field(pattern="^(fixed|percent)$")
    pay_for_shift_default: float = Field(ge=0)


class WorkplaceCreate(WorkplaceBase):
    id: NanoID  # client-generated nanoid


class WorkplaceUpdate(APIModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=100)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    service_percent_default: Optional[int] = Field(default=None, ge=0, le=100)
    shift_type_default: Optional[str] = Field(default=None, pattern="^(fixed|percent)$")
    pay_for_shift_default: Optional[float] = Field(default=None, ge=0)


class WorkplaceOut(WorkplaceBase):
    id: str
    owner_id: int
    position: int
    is_archived: bool
    created_at: int
    updated_at: int
    # Role of the requesting user (computed in service)
    my_role: str  # "owner" | "member"
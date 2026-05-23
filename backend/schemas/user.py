from typing import Optional
from pydantic import Field

from .common import APIModel


class UserOut(APIModel):
    id: int
    tg_id: int
    username: Optional[str]
    language: str
    timezone: str
    last_online_at: Optional[int]
    last_workplace_id: Optional[str]
    is_onboarding_completed: bool
    created_at: int
    updated_at: int


class UserUpdate(APIModel):
    language: Optional[str] = Field(default=None, min_length=2, max_length=10)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_onboarding_completed: Optional[bool] = None
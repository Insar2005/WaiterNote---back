from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, ConfigDict
from datetime import datetime, timezone
from typing import List, Optional
from models import User, Hall, Table, Shift, Order, MenuCategory, MenuItem, OrderItem, async_session

# ========== SCHEMAS ==========

# User Schemas
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    tg_id: int
    username: Optional[str] = None
    language: str
    place_work_title: Optional[str] = None
    timezone: str
    currency: str
    service_percent: int
    shift_type: str
    pay_for_shift: float


class UserCreate(BaseModel):
    tg_id: int
    username: Optional[str] = None
    language: str = "ru"
    place_work_title: Optional[str] = None
    timezone: str = "Europe/Moscow"
    currency: str = "RUB"
    service_percent: int = 0
    shift_type: str = "fixed"
    pay_for_shift: float = 0

class UserUpdate(BaseModel):
    username: Optional[str] = None
    language: Optional[str] = None
    place_work_title: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    service_percent: Optional[int] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None

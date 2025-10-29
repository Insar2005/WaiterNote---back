from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, ConfigDict
from datetime import datetime, timezone
from typing import List, Optional
from models import User, Hall, Table, Shift, Order, MenuCategory, MenuItem, OrderItem, async_session

# ========== SCHEMAS ==========
# Response Schemas
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
    shifts: "ShiftResponse" = None
    halls: List["HallResponse"] = []
    menu: List["MenuCategoryResponse"] = []

class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    start_time: datetime
    is_closed: bool
    end_time: Optional[datetime] = None
    place_work_title: Optional[str] = None
    currency: Optional[str] = None
    service_percent: Optional[int] = 0
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = 0
    total_pay_for_shift: Optional[float] = 0
    total_tips: Optional[float] = 0
    total_cash_register: Optional[float] = 0
    order_count: Optional[int] = 0
    orders: List["OrderResponse"] = []
    duration: Optional[int] = None
    created_at: datetime



class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    shift_id: int
    table_id: Optional[int] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
    comments: Optional[str] = None
    tips: float = 0
    total_price: float = 0
    is_paid: bool = False
    is_done: bool = False
    items: List["OrderItemResponse"] = []

class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    order_id: int
    menu_item_id: int
    title: str
    quantity: int
    price: float
    comment: Optional[str] = None

class MenuCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    title: str
    position: int
    items: List["MenuItemResponse"] = []

class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    category_id: int
    title: str
    description: Optional[str] = None
    portion: Optional[str] = None
    price: float
    position: int



class HallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    name: str
    position: int
    tables: List["TableResponse"] = []
class TableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    hall_id: int
    number: int
    x: int
    y: int
    width: int
    height: int
    rotation: int
    status: str
    current_order: Optional["OrderResponse"] = None


# Create Schemas

class UserCreate(BaseModel):
    tg_id: int
    username: Optional[str] = None
    language: str
    place_work_title: Optional[str] = None
    timezone: str
    currency: str
    service_percent: int = 0
    shift_type: str = "fixed"
    pay_for_shift: float = 0

class HallCreate(BaseModel):
    
    name: str
    position: int = 0
class TableCreate(BaseModel):
    
    number: int
    x: int
    y: int
    width: int = 100
    height: int = 100
    rotation: int = 0
    border_radius: int = 15
    status: str = "free"
class OrderCreate(BaseModel):
    
    table_id: Optional[int] = None
    table_number: Optional[int] = None
    hall_name: Optional[str] = None
    comments: Optional[str] = None
    total_price: float = 0
    items: List["OrderItemCreate"]

class OrderItemCreate(BaseModel):
    menu_item_id: int
    title: str
    quantity: int
    price: float
    comment: Optional[str] = None


class ShiftCreate(BaseModel):
    
    start_time: datetime
    is_closed: bool = False
    place_work_title: Optional[str] = None
    currency: Optional[str] = None
    service_percent: Optional[int] = 0
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = 0
    order_count: Optional[int] = 0
    
class MenuCategoryCreate(BaseModel):
    user_id: int
    title: str
    position: int = 0
class MenuItemCreate(BaseModel):
    
    title: str
    description: Optional[str] = None
    portion: Optional[str] = None
    price: float
    position: int = 0

# Update Schemas
class UserUpdate(BaseModel):
    username: Optional[str] = None
    language: Optional[str] = None
    place_work_title: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    service_percent: Optional[int] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None
    updated_at: Optional[datetime] = None

class HallUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None

class TableUpdate(BaseModel):
    number: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    rotation: Optional[int] = None
    border_radius: Optional[int] = None
    status: Optional[str] = None

class MenuCategoryUpdate(BaseModel):
    title: Optional[str] = None
    position: Optional[int] = None

class MenuItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    portion: Optional[str] = None
    price: Optional[float] = None
    position: Optional[int] = None

class ShiftUpdate(BaseModel):
    is_closed: Optional[bool] = None
    end_time: Optional[datetime] = None
    place_work_title: Optional[str] = None
    currency: Optional[str] = None
    service_percent: Optional[int] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None
    total_pay_for_shift: Optional[float] = None
    total_tips: Optional[float] = None
    total_cash_register: Optional[float] = None
    order_count: Optional[int] = None
    duration: Optional[int] = None

class OrderUpdate(BaseModel):
    table_id: Optional[int] = None
    table_number: Optional[int] = None
    hall_name: Optional[str] = None
    closed_at: Optional[datetime] = None
    comments: Optional[str] = None
    tips: Optional[float] = None
    total_price: Optional[float] = None
    is_paid: Optional[bool] = None
    is_done: Optional[bool] = None

class OrderItemUpdate(BaseModel):
    
    title: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    comment: Optional[str] = None
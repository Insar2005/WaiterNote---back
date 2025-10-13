from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload
from models import Hall, Map, MenuCategory, MenuItem, Order, async_session, User, Table
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import List, Optional

class UserInfoResponse(BaseModel):
    id: int
    tg_id: int
    sign_in_date: datetime
    username: str
    title_place_work: Optional[str]
    language: str
    timezone: str
    currency: str
    shift_type: str
    pay_for_shift: float

class MenuItemResponse(BaseModel):
    id: int
    item_title: str
    price: float
    item_position: int

class MenuCategoryResponse(BaseModel):
    id: int
    title: str
    position: int
    menu_items: List[MenuItemResponse] = []

class TableResponse(BaseModel):
    id: int
    table_number: int
    status: str
    rotation: int
    corner_radius: int
    width: int
    height: int
    pos_x: int
    pos_y: int

class HallResponse(BaseModel):
    id: int
    hall_title: str
    hall_position: int
    tables_info: List[TableResponse] = []

class MapResponse(BaseModel):
    id: int
    halls_info: List[HallResponse] = []


class OrderItemResponse(BaseModel):
    id: int
    item_title: str
    price: float
    quantity: int
    total_price: float
    comments: Optional[str]

class OrderResponse(BaseModel):
    id: int
    hall_name: Optional[str]
    table_number: Optional[int]
    order_date: datetime
    total_price: float
    tips: float
    tax: float
    status: str
    comments: Optional[str]
    order_items: List[OrderItemResponse] = []

class WorkShiftResponse(BaseModel):
    id: int
    date: datetime
    start_time: datetime
    end_time: Optional[datetime]
    total_orders: int
    total_pay_for_shift: float
    total_cash_register: float
    total_tips: float
    is_closed: bool
    orders: List[OrderResponse] = []

class UserCreate(BaseModel):
    tg_id: int
    username: str
    title_place_work: Optional[str] = None
    language: Optional[str] = "en"
    timezone: Optional[str] = "+03:00"
    currency: Optional[str] = "USD"
    shift_type: Optional[str] = "fixed"
    pay_for_shift: Optional[float] = 0.0

class MenuItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    position: Optional[int] = 0

class MenuCategoryCreate(BaseModel):
    title: str
    position: Optional[int] = 0
    menu_items: Optional[list[MenuItemCreate]] = []

class TableCreate(BaseModel):
    table_number: int
    pos_x: int
    pos_y: int
    width: int
    height: int
    rotation: int = 0
    corner_radius: int = 0

class HallCreate(BaseModel):
    hall_name: str
    position: Optional[int] = 0
    tables: Optional[list[TableCreate]] = []

class MapCreate(BaseModel):
    halls: Optional[list[HallCreate]] = []

class OrderItemCreate(BaseModel):
    item_id: int
    quantity: int = 1
    comments: Optional[str] = None

class OrderCreate(BaseModel):
    hall_id: Optional[int] = None
    table_id: Optional[int] = None
    comments: Optional[str] = None
    order_items: list[OrderItemCreate]

class WorkShiftCreate(BaseModel):
    start_time: datetime
    orders: Optional[list[OrderCreate]] = []


class UserUpdate(BaseModel):
    username: Optional[str] = None
    title_place_work: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None


class MenuItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    position: Optional[int] = None

class MenuCategoryUpdate(BaseModel):
    title: Optional[str] = None
    position: Optional[int] = None

class TableUpdate(BaseModel):
    table_number: Optional[int] = None
    pos_x: Optional[int] = None
    pos_y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    rotation: Optional[int] = None
    corner_radius: Optional[int] = None

class HallUpdate(BaseModel):
    hall_name: Optional[str] = None
    position: Optional[int] = None


class OrderItemUpdate(BaseModel):
    quantity: Optional[int] = None
    comments: Optional[str] = None

class OrderUpdate(BaseModel):
    hall_id: Optional[int] = None
    table_id: Optional[int] = None
    comments: Optional[str] = None
    status: Optional[str] = None  # например: "open", "paid", "cancelled"

class WorkShiftUpdate(BaseModel):
    end_time: Optional[datetime] = None
    is_closed: Optional[bool] = None

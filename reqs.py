from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal

class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category_id: str
    title: str
    description: Optional[str]
    portion: Optional[str]
    price: float
    position: int

class MenuCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: int
    title: str
    position: int
    items: List[MenuItemResponse] = Field(default_factory=list)

class TableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hall_id: str
    number: int
    x: float
    y: float
    width: int
    height: int
    rotation: int
    border_radius: int
    status: str
    order_id: Optional[str] = None

class HallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: int
    name: str
    position: int
    tables: List[TableResponse] = Field(default_factory=list)

class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_id: str
    menu_item_id: Optional[str]
    title: str
    price: float
    quantity: int
    comment: Optional[str]

class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    shift_id: str
    hall_id: str
    table_id: Optional[str]
    table_number: Optional[int]
    hall_name: Optional[str]
    created_at: int
    updated_at: int
    closed_at: Optional[int]
    comments: Optional[str]
    tips: Optional[float]
    total_price: float
    is_paid: bool
    is_done: bool
    items: List[OrderItemResponse] = Field(default_factory=list)

class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: int
    start_time: int
    is_closed: bool
    end_time: Optional[int]
    place_work_title: str
    currency: str
    service_percent: int
    shift_type: str
    pay_for_shift: float
    total_pay_for_shift: float
    total_tips: float
    total_cash_register: float
    order_count: int
    duration: int
    orders: List[OrderResponse] = Field(default_factory=list)

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tg_id: int
    username: str
    language: str
    place_work_title: str
    timezone: str
    currency: str
    service_percent: int
    shift_type: str
    pay_for_shift: float
    created_at: int
    updated_at: int
    shifts: List[ShiftResponse] = Field(default_factory=list)
    menu: List[MenuCategoryResponse] = Field(default_factory=list)
    halls: List[HallResponse] = Field(default_factory=list)


# Схемы для создания записей

class MenuItemCreate(BaseModel):
    id:str
    category_id: str
    title: str
    description: Optional[str] = None
    portion: Optional[str] = None
    price: float
    position: int = 0

class MenuCategoryCreate(BaseModel):
    id:str
    title: str
    position: int = 0
    items: Optional[List[MenuItemCreate]] = []

class TableCreate(BaseModel):
    id:str
    hall_id: str
    number: int
    x: float = 0
    y: float = 0
    width: int = 100
    height: int = 100
    rotation: int = 0
    border_radius: int = 15
    status: str = "free"

class HallCreate(BaseModel):
    id:str
    name: str
    position: int = 0
    tables: Optional[List[TableCreate]] = []

class OrderItemCreate(BaseModel):
    id:str
    order_id: str
    menu_item_id: Optional[str] = None
    title: str
    price: float
    quantity: int = 1
    comment: Optional[str] = None

class OrderCreate(BaseModel):
    id:str
    shift_id: str
    table_id: Optional[str] = None
    table_number: Optional[int] = None
    hall_name: Optional[str] = None
    comments: Optional[str] = None
    total_price: float = 0
    items: List[OrderItemCreate]

class ShiftCreate(BaseModel):
    id:str

    start_time: int
    place_work_title: str = "Waiter Note"
    currency: str = "USD"
    service_percent: int = 0
    shift_type: str = "fixed"
    pay_for_shift: float = 0

class UserCreate(BaseModel):
    tg_id: int
    username: str
    language: str = "ru"
    place_work_title: str = "Waiter Note"
    timezone: str = "Europe/Moscow"
    currency: str = "RUB"
    service_percent: int = 0
    shift_type: str = "fixed"
    pay_for_shift: float = 0


# Схемы для обновления записей

class MenuItemUpdate(BaseModel):
    
    title: Optional[str] = None
    description: Optional[str] = None
    portion: Optional[str] = None
    price: Optional[float] = None
    position: Optional[int] = None

class MenuCategoryUpdate(BaseModel):
    title: Optional[str] = None
    position: Optional[int] = None

class TableUpdate(BaseModel):
    order_id:Optional[str] = None
    number: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    rotation: Optional[int] = None
    border_radius: Optional[int] = None
    status: Optional[str] = None

class HallUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None

class OrderItemUpdate(BaseModel):
    menu_item_id: Optional[int] = None
    title: Optional[str] = None
    price: Optional[float] = None
    total_price: Optional[float] = None
    quantity: Optional[int] = None
    comment: Optional[str] = None

class OrderUpdate(BaseModel):
    table_id: Optional[int] = None
    table_number: Optional[int] = None
    hall_name: Optional[str] = None
    comments: Optional[str] = None
    tips: Optional[float] = None
    total_price: Optional[float] = None
    is_paid: Optional[bool] = None
    is_done: Optional[bool] = None
    closed_at: Optional[int] = None
    items: Optional[List[OrderItemUpdate]] = None

class ShiftUpdate(BaseModel):
    is_closed: Optional[bool] = None
    end_time: Optional[int] = None
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

class UserUpdate(BaseModel):
    username: Optional[str] = None
    language: Optional[str] = None
    place_work_title: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    service_percent: Optional[int] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None

class SyncOperation(BaseModel):
    id: str                    
    user_id: int               
    entity: str                
    action: Literal["add", "update", "delete"]
    payload: dict    

    #sdfkf
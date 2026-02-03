from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


# =========================
# USER
# =========================

class UserCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    tg_id: int
    username: Optional[str] = None
    language: str
    timezone: str



class WorkPlaceList(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    position: int
    is_archived: bool

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_id: int
    username: Optional[str] = None

    language: str
    timezone: str

    last_online_at: Optional[int] = None
    last_workplace_id: Optional[str] = None

    is_onboarding_completed: bool
    is_disabled: bool

    created_at: int
    updated_at: int

    # ВАЖНО:
    # - из ORM читаем user.workplaces
    # - наружу отдаем как "wpList"
    workplaces: List[WorkPlaceList] = Field(default_factory=list)#, serialization_alias="wpList")


class UserPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # tg_id обычно не патчим (уникальный ключ), но оставлю опционально если нужно
    username: Optional[str] = None

    language: Optional[str] = None
    timezone: Optional[str] = None

    last_online_at: Optional[int] = None
    last_workplace_id: Optional[str] = None

    is_onboarding_completed: Optional[bool] = None
    is_disabled: Optional[bool] = None


# =========================
# WORKPLACE
# =========================
class WorkplaceCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    user_id: int

    title: str
    timezone: str
    currency: str

    service_percent_default: int = Field( default=10, ge=0, le=100)
    shift_type_default: str = "standard"
    pay_for_shift_default: float = 0.0

    position: int = 0
    is_archived: bool = False
class WorkplaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int

    title: str
    timezone: str
    currency: str

    service_percent_default: int
    shift_type_default: str
    pay_for_shift_default: float

    position: int
    is_archived: bool

    created_at: int
    updated_at: int


class WorkplacePatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None

    service_percent_default: Optional[int] = Field(default=None, ge=0, le=100)
    shift_type_default: Optional[str] = None
    pay_for_shift_default: Optional[float] = None

    position: Optional[int] = None
    is_archived: Optional[bool] = None


# =========================
# SHIFT
# =========================
class ShiftCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    workplace_id: str

    start_time: int
    
    place_work_title: str
    currency: str
    service_percent: int = Field( default=10, ge=0, le=100)
    shift_type: str = "standard"
    pay_for_shift: float = 0.0
    
class ShiftInHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    start_time: int
    end_time: int
    total_pay_for_shift: float
    total_tips: float
    total_cash_register: float
    duration: int
    order_count: int
    is_closed: bool
class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workplace_id: str

    start_time: int
    is_closed: bool
    end_time: int

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
    orders: Optional[List[OrderResponse]] = []


class ShiftPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # обычно start_time не патчим, но если надо — можно
    is_closed: Optional[bool] = None
    end_time: Optional[int] = None

    # snapshot-поля можно запретить к патчу, но оставляю опционально
    place_work_title: Optional[str] = None
    currency: Optional[str] = None
    service_percent: Optional[int] = Field(default=None, ge=0, le=100)
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None

    total_pay_for_shift: Optional[float] = None
    total_tips: Optional[float] = None
    total_cash_register: Optional[float] = None

    order_count: Optional[int] = None
    duration: Optional[int] = None


# =========================
# ORDER
# =========================
class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    shift_id: str
    hall_id: Optional[str] = None
    table_id: Optional[str] = None

    table_number: Optional[int] = None
    hall_name: Optional[str] = None

    comments: Optional[str] = None

    created_at: int

    tips: float = 0.0
    total_price: float = 0.0

    is_paid: bool = False
    is_done: bool = False
    items: Optional[List[OrderItemCreateRequest]] = []

class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    shift_id: str
    hall_id: Optional[str] = None
    table_id: Optional[str] = None

    table_number: Optional[int] = None
    hall_name: Optional[str] = None

    comments: Optional[str] = None

    created_at: int
    updated_at: int
    closed_at: int

    tips: float
    total_price: float

    is_paid: bool
    is_done: bool
    items: List[OrderItemResponse] = Field(default_factory=list)


class OrderPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # связи/ссылки
    hall_id: Optional[str] = None
    table_id: Optional[str] = None

    # snapshot-поля
    table_number: Optional[int] = None
    hall_name: Optional[str] = None

    comments: Optional[str] = None

    closed_at: Optional[int] = None
    tips: Optional[float] = None
    total_price: Optional[float] = None

    is_paid: Optional[bool] = None
    is_done: Optional[bool] = None
    items: Optional[List[OrderItemCreateRequest]] = None


# =========================
# ORDER ITEM
# =========================
class OrderItemCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    order_id: str

    menu_item_id: Optional[str] = None

    title: str
    price: float
    quantity: int = Field( default=1, ge=1)
    total_price: float

    comment: Optional[str] = None

class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    menu_item_id: Optional[str] = None

    title: str
    price: float
    quantity: int
    total_price: float

    comment: Optional[str] = None


class OrderItemPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_item_id: Optional[str] = None

    title: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = Field(default=None, ge=1)
    total_price: Optional[float] = None

    comment: Optional[str] = None


# =========================
# NOTES
# =========================
class NotesCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    user_id: int

    scope: str
    workplace_id: Optional[str] = None
    shift_id: Optional[str] = None

    header: str
    content: Optional[str] = None

    pinned: bool = False
    archived: bool = False
class NotesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int

    scope: str
    workplace_id: Optional[str] = None
    shift_id: Optional[str] = None

    header: str
    content: Optional[str] = None

    pinned: bool
    archived: bool

    created_at: int
    updated_at: int


class NotesPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scope: Optional[str] = None
    workplace_id: Optional[str] = None
    shift_id: Optional[str] = None

    header: Optional[str] = None
    content: Optional[str] = None

    pinned: Optional[bool] = None
    archived: Optional[bool] = None


# =========================
# HALL
# =========================
class HallCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    workplace_id: str

    name: str
    position: int = 0

    width: int
    height: int
    scale: float = 1.0
class HallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workplace_id: str

    name: str
    position: int

    width: int
    height: int
    scale: float
    tables: Optional[List[TableResponse]] = []


class HallPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Optional[str] = None
    position: Optional[int] = None

    width: Optional[int] = None
    height: Optional[int] = None
    scale: Optional[float] = None


# =========================
# TABLE
# =========================
class TableCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    hall_id: str

    order_id: Optional[str] = None
    number: int

    x: float
    y: float

    width: int
    height: int

    rotation: int = 0
    border_radius: int = 0

    status: str = "free"

class TableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hall_id: str

    order_id: Optional[str] = None
    number: int

    x: float
    y: float

    width: int
    height: int

    rotation: int
    border_radius: int

    status: str


class TablePatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: Optional[str] = None
    number: Optional[int] = None

    x: Optional[float] = None
    y: Optional[float] = None

    width: Optional[int] = None
    height: Optional[int] = None

    rotation: Optional[int] = None
    border_radius: Optional[int] = None

    status: Optional[str] = None


# =========================
# MENU CATEGORY
# =========================
class MenuCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    workplace_id: str

    title: str

    position: int = 0
    is_active: bool = True
class MenuCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workplace_id: str

    title: str
    position: int
    is_active: bool
    items: Optional[List[MenuItemResponse]] = []


class MenuCategoryPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: Optional[str] = None
    position: Optional[int] = None
    is_active: Optional[bool] = None


# =========================
# MENU ITEM
# =========================

class MenuItemCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    category_id: str

    title: str
    description: Optional[str] = None
    portion: Optional[str] = None

    price: float

    position: int = 0
    is_active: bool = True
class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category_id: str

    title: str
    description: Optional[str] = None
    portion: Optional[str] = None

    price: float

    position: int
    is_active: bool


class MenuItemPatchUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: Optional[str] = None
    description: Optional[str] = None
    portion: Optional[str] = None

    price: Optional[float] = None

    position: Optional[int] = None
    is_active: Optional[bool] = None


# =========================
# (Опционально) Response с вложениями для удобных ручек API
# =========================

class OrderWithItemsResponse(OrderResponse):
    model_config = ConfigDict(from_attributes=True)
    items: List[OrderItemResponse] = []


class WorkplaceFullResponse(WorkplaceResponse):
    model_config = ConfigDict(from_attributes=True)
    halls: List[HallResponse] = []
    menu_categories: List[MenuCategoryResponse] = []
    shifts: List[ShiftResponse] = []


class HallWithTablesResponse(HallResponse):
    model_config = ConfigDict(from_attributes=True)
    tables: List[TableResponse] = []

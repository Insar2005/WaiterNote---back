from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload
from models import Hall, Map, MenuCategory, MenuItem, Order, async_session, User, Table
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import List, Optional
from models import User, Map, Hall, Table, WorkShift, Order, OrderItem, MenuItem, MenuCategory

class UserInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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

async def get_user_info_by_tg_id(tg_id: int) -> UserInfoResponse | None:
    async with async_session() as session:
        
        user_info = await session.scalar(
            select(User)
            
            .where(User.tg_id == tg_id)
        )
        
        if user_info:
            return UserInfoResponse.model_validate(user_info)
        return None
class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    item_title: str
    price: float
    item_position: int

class MenuCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    position: int
    menu_items: List[MenuItemResponse] = []

class TableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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
    model_config = ConfigDict(from_attributes=True)
    id: int
    hall_title: str
    hall_position: int
    tables_info: List[TableResponse] = []

class MapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    halls_info: List[HallResponse] = []


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    item_title: str
    price: float
    quantity: int
    total_price: float
    comments: Optional[str]

class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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
    model_config = ConfigDict(from_attributes=True)
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
    model_config = ConfigDict(from_attributes=True)
    tg_id: int
    username: str
    title_place_work: Optional[str] = None
    language: Optional[str] = "en"
    timezone: Optional[str] = "+03:00"
    currency: Optional[str] = "USD"
    shift_type: Optional[str] = "fixed"
    pay_for_shift: Optional[float] = 0.0

async def add_new_user(user_data: UserCreate) -> UserInfoResponse:
    async with async_session() as session:
        user_info_model = User(**user_data.model_dump())  # ✅ можно сразу передать dict
        session.add(user_info_model)
        await session.commit()
        await session.refresh(user_info_model)
        return UserInfoResponse.model_validate(user_info_model)
class MenuItemCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_title: str
    
    price: float
    item_position: Optional[int] = 0
    category_id: int

async def create_new_item(item_data: MenuItemCreate) -> MenuItemResponse:
    async with async_session() as session:
        new_item = MenuItem(
            category_id=item_data.category_id,
            item_title = item_data.item_title,
            item_position = item_data.item_position,
            price = item_data.price
        )
        session.add(new_item)
        await session.commit()
        await session.refresh(new_item)
        return MenuItemResponse.model_validate(new_item)
class MenuCategoryCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str
    position: Optional[int] = 0
    menu_items: Optional[list[MenuItemCreate]] = []



async def create_new_category(tg_id: int, create_data: MenuCategoryCreate) -> MenuCategoryResponse:
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            raise ValueError("User not found")

        new_category = MenuCategory(
            user_id=user.id,
            title=create_data.title,
            position=create_data.position,
        )
        session.add(new_category)
        await session.commit()

        # Загружаем с подгрузкой menu_items
        category = await session.scalar(
            select(MenuCategory)
            .options(selectinload(MenuCategory.menu_items))
            .where(MenuCategory.id == new_category.id)
        )

        return MenuCategoryResponse.model_validate(category)

async def delete_category(c_id:int)->bool:
    async with async_session() as session:
        category = await session.get(MenuCategory, c_id)
        if not category:
            return True
        await session.delete(category)
        await session.commit()
        return True
async def delete_item(i_id:int)->bool:
    async with async_session() as session:
        item = await session.get(MenuItem, i_id)
        if not item:
            return True
        await session.delete(item)
        await session.commit()
        return True
class TableCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    table_number: int
    pos_x: int
    pos_y: int
    width: int
    height: int
    rotation: int = 0
    corner_radius: int = 0

class HallCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    hall_name: str
    position: Optional[int] = 0
    tables: Optional[list[TableCreate]] = []

class MapCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    halls: Optional[list[HallCreate]] = []

class OrderItemCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_id: int
    quantity: int = 1
    comments: Optional[str] = None

class OrderCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    hall_id: Optional[int] = None
    table_id: Optional[int] = None
    comments: Optional[str] = None
    order_items: list[OrderItemCreate]

class WorkShiftCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    start_time: datetime
    orders: Optional[list[OrderCreate]] = []


class UserUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: Optional[str] = None
    title_place_work: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None

async def update_user_info(tg_id=int, update_data = UserUpdate)->UserInfoResponse:
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id==tg_id))
        if not user:
            return None
        for field, value in update_data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)

        session.add(user)
        await session.commit()
        await session.refresh(user)

    # Возвращаем Pydantic ответ
        return UserInfoResponse.model_validate(user)
class MenuItemUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    position: Optional[int] = None

async def menu_item_update(id:int, update_data:MenuItemUpdate) ->MenuItemResponse | None:
    async with async_session() as session:
        item = await session.get(MenuItem, id)
        if not item:
            return None
        for field, value in update_data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        
        await session.commit()
        await session.refresh(item)
        return MenuItemResponse.model_validate(item)
class MenuCategoryUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    title: Optional[str] = None
    position: Optional[int] = None

async def menu_update(category_id:int,update_data: MenuCategoryUpdate)->MenuCategoryResponse | None:
    async with async_session() as session:
        category = await session.get(MenuCategory, category_id)
        if not category:
            return None
        for field, value in update_data.model_dump(exclude_unset=True).items():
            setattr(category, field, value)

        await session.commit()
        await session.refresh(category)
        return MenuCategoryUpdate.model_validate(category)


async def get_user_menu_with_items(tg_id: int)->MenuCategoryResponse:
    async with async_session() as session:
        categoryes = await session.scalars(
            select(MenuCategory).join(User, MenuCategory.user_id == User.id).where(User.tg_id==tg_id).options(selectinload(MenuCategory.menu_items)).order_by(MenuCategory.position) 
        )
        if not categoryes:
            return None
        categories_list = list(categoryes)
        return [MenuCategoryResponse.model_validate(cat) for cat in categories_list]
class TableUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    table_number: Optional[int] = None
    pos_x: Optional[int] = None
    pos_y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    rotation: Optional[int] = None
    corner_radius: Optional[int] = None

class HallUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    hall_name: Optional[str] = None
    position: Optional[int] = None


class OrderItemUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    quantity: Optional[int] = None
    comments: Optional[str] = None

class OrderUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    hall_id: Optional[int] = None
    table_id: Optional[int] = None
    comments: Optional[str] = None
    status: Optional[str] = None  # например: "open", "paid", "cancelled"

class WorkShiftUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    end_time: Optional[datetime] = None
    is_closed: Optional[bool] = None

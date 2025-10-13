from sqlalchemy import ForeignKey, String,Float, BigInteger, Text, Integer
from sqlalchemy.orm import Mapped,  DeclarativeBase, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from typing import Optional, List
from datetime import datetime, timezone 
#Здесь создаем и подключаемся к бд
engine = create_async_engine(url='sqlite+aiosqlite:///db.sqlite3', echo = True)

async_session = async_sessionmaker(bind = engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    sign_in_date: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    username: Mapped[str] = mapped_column(String(128))
    title_place_work: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(6), default="en")
    timezone: Mapped[str] = mapped_column(String(6), default="+03:00")
    currency: Mapped[str] = mapped_column(String(6), default="USD")
    shift_type: Mapped[str] = mapped_column(String(128), default="fixed")
    pay_for_shift: Mapped[float] = mapped_column(Float, default=0.0)

    # Связи
    menu_categories: Mapped[List["MenuCategory"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    work_shifts: Mapped[List["WorkShift"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    map_info: Mapped[List["Map"]] = relationship(back_populates="user", cascade="all, delete-orphan")  

class Map(Base):
    __tablename__='maps'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    user: Mapped["User"] = relationship(back_populates='map_info')
    halls_info: Mapped[List["Hall"]] = relationship(back_populates="map", cascade="all, delete-orphan")

class Hall(Base):
    __tablename__='halls'
    id: Mapped[int] = mapped_column(primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey('maps.id', ondelete="CASCADE"))
    hall_title: Mapped[str] = mapped_column(String(128))
    hall_position: Mapped[int] = mapped_column(Integer, default=0)
    tables_info: Mapped[List["Table"]] = relationship(back_populates="hall")
    map: Mapped["Map"]=relationship(back_populates="halls_info")

class Table(Base):
    __tablename__ = 'tables'

    id: Mapped[int] = mapped_column(primary_key=True)
    current_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey('orders.id'), nullable=True)
    hall_id:Mapped[int]= mapped_column(ForeignKey('halls.id'), nullable=True)
    table_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64), default="free")  # free, waiting, no pay, payed
    #settings
    rotation: Mapped[int] = mapped_column(Integer, default=0)  # угол поворота стола на плане -180..180
    corner_radius: Mapped[int] = mapped_column(Integer, default=0)  # радиус скругления углов стола на плане 0..100
    width: Mapped[int] = mapped_column(Integer, default=100)  # ширина стола на плане в пикселях
    height: Mapped[int] = mapped_column(Integer, default=100)  # высота стола на плане в пикселях
    pos_x: Mapped[int] = mapped_column(Integer, default=0)  # координата X на плане
    pos_y: Mapped[int] = mapped_column(Integer, default=0)  # координата Y на плане
    # Связи
    hall: Mapped["Hall"] = relationship(back_populates="tables_info")
    

class WorkShift(Base):
    __tablename__ = 'work_shifts'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    date: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    start_time: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    end_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    shift_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # in seconds
    
    # Статистика (лучше вычислять, чем хранить)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    total_pay_for_shift: Mapped[float] = mapped_column(Float, default=0.0)
    total_cash_register: Mapped[float] = mapped_column(Float, default=0.0)
    total_tips: Mapped[float] = mapped_column(Float, default=0.0)
    
    is_closed: Mapped[bool] = mapped_column(default=False)

    # Связи
    user: Mapped["User"] = relationship(back_populates="work_shifts")
    orders: Mapped[List["Order"]] = relationship(back_populates="work_shift", cascade="all, delete-orphan")  # исправлено имя!


class Order(Base):
    __tablename__ = 'orders'

    id: Mapped[int] = mapped_column(primary_key=True)
    work_shift_id: Mapped[int] = mapped_column(ForeignKey('work_shifts.id'), nullable=True)  
    hall_id: Mapped[Optional[int]] = mapped_column(ForeignKey('halls.id'), nullable=True)
    table_id: Mapped[Optional[int]] = mapped_column(ForeignKey('tables.id'), nullable=True)
    table_number: Mapped[int] = mapped_column(nullable=True)  # номер стола
    hall_name: Mapped[str] = mapped_column(String(128), nullable=True)  # название зала
    order_date: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    total_price: Mapped[float] = mapped_column(Float, default=0.0)
    tips: Mapped[float] = mapped_column(Float, default=0.0)
    tax: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="in_progress")  # in_progress, completed, cancelled
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Связи
    
    work_shift: Mapped["WorkShift"] = relationship(back_populates="orders")  # исправлено имя!
    order_items: Mapped[List["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = 'order_items'

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'))
    
    # Ссылка на товар в меню (опционально - товар может быть удален)
    menu_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey('menu_items.id'), nullable=True)
    
    # Сохраняем данные на момент заказа
    item_title: Mapped[str] = mapped_column(String(128))
    price: Mapped[float] = mapped_column(Float)  # цена за единицу на момент заказа
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_price: Mapped[float] = mapped_column(Float)  # price * quantity
    item_position: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Связи
    order: Mapped["Order"] = relationship(back_populates="order_items")
    menu_item: Mapped[Optional["MenuItem"]] = relationship("MenuItem")

    

class MenuItem(Base):
    __tablename__ = 'menu_items'

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey('menu_categories.id'), nullable=True)
    item_title: Mapped[str] = mapped_column(String(128))
    price: Mapped[float] = mapped_column(Float, default=0.0)
    item_position: Mapped[int] = mapped_column(Integer, default=0)

    # Связь с категорией
    category: Mapped["MenuCategory"] = relationship(back_populates="menu_items")

class MenuCategory(Base):
    __tablename__ = 'menu_categories'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer, default=0)

    # Связи
    user: Mapped["User"] = relationship(back_populates="menu_categories")
    menu_items: Mapped[List["MenuItem"]] = relationship(back_populates="category", cascade="all, delete-orphan")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
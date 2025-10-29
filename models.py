from sqlalchemy import ForeignKey, String, Float, BigInteger, Text, Integer, Boolean, Numeric, TIMESTAMP
from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from typing import Optional, List
from datetime import datetime, timezone as timeZone
import asyncpg
import asyncio
import ssl, os


# === Подключение к БД ===
ssl_context = ssl.create_default_context(
    cafile=os.path.expanduser("./.cloud_cert/ca.crt")
)

engine = create_async_engine(
    url="postgresql+asyncpg://gen_user:Pa;Q)i&^rlVs3M@10991957a615ef4315a8f228.twc1.net:5432/WaiterNote",
    connect_args={"ssl": ssl_context},
    echo=True,
)

async_session = async_sessionmaker(bind=engine, expire_on_commit=False)


# === Базовый класс ===
class Base(AsyncAttrs, DeclarativeBase):
    pass


# === МОДЕЛИ ===

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(10), default="ru")
    place_work_title: Mapped[Optional[str]] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow")
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    service_percent: Mapped[int] = mapped_column(Integer, default=0)
    shift_type: Mapped[str] = mapped_column(String(20), default="fixed")
    pay_for_shift: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    shifts: Mapped[Optional[List["Shift"]]] = relationship(back_populates="user", cascade="all, delete")
    halls: Mapped[Optional[List["Hall"]]] = relationship(back_populates="user", cascade="all, delete")
    menu: Mapped[Optional[List["MenuCategory"]]] = relationship(back_populates="user", cascade="all, delete")

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now(tz=timeZone.utc))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now(tz=timeZone.utc))


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    start_time: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now(tz=timeZone.utc))
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, default=datetime.now(tz=timeZone.utc))
    place_work_title: Mapped[Optional[str]] = mapped_column(String(255))
    currency: Mapped[Optional[str]] = mapped_column(String(10))
    service_percent: Mapped[Optional[int]]
    shift_type: Mapped[Optional[str]]
    pay_for_shift: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    total_pay_for_shift: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    total_tips: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), default=0)
    total_cash_register: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), default=0)
    order_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    duration: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="shifts")
    orders: Mapped[List["Order"]] = relationship(back_populates="shift", cascade="all, delete")


class Hall(Base):
    __tablename__ = "halls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="halls")
    tables: Mapped[List["Table"]] = relationship(back_populates="hall", cascade="all, delete")


class Table(Base):
    __tablename__ = "tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id", ondelete="CASCADE"))
    number: Mapped[int]
    x: Mapped[int]
    y: Mapped[int]
    width: Mapped[int] = mapped_column(Integer, default=100)
    height: Mapped[int] = mapped_column(Integer, default=100)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    border_radius: Mapped[int] = mapped_column(Integer, default=15)
    status: Mapped[str] = mapped_column(String(20), default="free")

    hall: Mapped["Hall"] = relationship(back_populates="tables")
    current_order: Mapped[Optional["Order"]] = relationship(back_populates="table", uselist=False) # uselist это для one-to-one отношений 


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="menu")
    items: Mapped[List["MenuItem"]] = relationship(back_populates="category", cascade="all, delete")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("menu_categories.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[Optional[str]] = mapped_column(Text)
    portion: Mapped[Optional[str]] = mapped_column(String(50))
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    position: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped["MenuCategory"] = relationship(back_populates="items")
    # order_items: Mapped[List["OrderItem"]] = relationship(back_populates="menu_item")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="CASCADE"))
    table_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tables.id", ondelete="SET NULL"))
    table_number: Mapped[Optional[int]] = mapped_column(Integer)
    hall_name: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now(tz=timeZone.utc))
    closed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, default=datetime.now(tz=timeZone.utc))
    comments: Mapped[Optional[str]] = mapped_column(Text)
    tips: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), default=0)
    total_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)

    shift: Mapped["Shift"] = relationship(back_populates="orders")
    table: Mapped["Table"] = relationship(back_populates="current_order")
    items: Mapped[List["OrderItem"]] = relationship(back_populates="order", cascade="all, delete")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    menu_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("menu_items.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(150))
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    comment: Mapped[Optional[str]] = mapped_column(Text)

    order: Mapped["Order"] = relationship(back_populates="items")
    # menu_item: Mapped["MenuItem"] = relationship(back_populates="order_items")


# === ИНИЦИАЛИЗАЦИЯ БД ===
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Tables created successfully")



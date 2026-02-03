from __future__ import annotations

import enum
import os
import ssl
from datetime import datetime, timezone as timeZone
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Enum as SAEnum,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# =========================
# Helpers / Types
# =========================

def utc_ts() -> int:
    """UTC unix timestamp (seconds). Must be callable for SQLAlchemy defaults."""
    return int(datetime.now(timeZone.utc).timestamp())


ID21 = String(21)

# Numeric types (asdecimal=False -> SQLAlchemy returns float)
MONEY = Numeric(10, 2, asdecimal=False)
COORD = Numeric(10, 2, asdecimal=False)
SCALE = Numeric(5, 2, asdecimal=False)


# =========================
# DB Connection
# =========================

# === Подключение к БД ===
ssl_context = ssl.create_default_context(
    cafile=os.path.expanduser("./.cloud_cert/ca.crt")
)

engine = create_async_engine(
    url="postgresql+asyncpg://gen_user:Pa;Q)i&^rlVs3M@10991957a615ef4315a8f228.twc1.net:5432/WaiterNote",
    connect_args={"ssl": ssl_context},
    echo=True,pool_recycle=1800
)

async_session = async_sessionmaker(bind=engine, expire_on_commit=False)


# =========================
# Enums
# =========================

TableStatus = SAEnum(
    "free",
    "waiting",
    "occupied",
    "reserved",
    name="table_status",
)


class NoteScope(str, enum.Enum):
    global_ = "global"
    workplace = "workplace"
    shift = "shift"


# =========================
# Base
# =========================

class Base(AsyncAttrs, DeclarativeBase):
    pass


# =========================
# Models (MVP v1: no bills splitting, no courses)
# =========================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    language: Mapped[str] = mapped_column(String(10), default="ru", nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow", nullable=False)

    last_online_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    last_workplace_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workplaces.id", ondelete="SET NULL"),
        nullable=True,
    )


    is_onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[int] = mapped_column(Integer, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=utc_ts, onupdate=utc_ts, nullable=False)

    # Relationships
    workplaces: Mapped[List["Workplace"]] = relationship(
        "Workplace",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="Workplace.user_id",
    )

    # convenience pointer (optional)
    last_workplace: Mapped[Optional["Workplace"]] = relationship(
        "Workplace",
        foreign_keys=[last_workplace_id],
        post_update=True,
    )

    notes: Mapped[List["Notes"]] = relationship(
        "Notes",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Workplace(Base):
    __tablename__ = "workplaces"

    __table_args__ = (
        CheckConstraint(
            "service_percent_default >= 0 AND service_percent_default <= 100",
            name="ck_workplaces_service_percent_range",
        ),
        Index("ix_workplaces_user_position", "user_id", "position"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    user_id: Mapped[int] = mapped_column(BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(255), default="Waiter Note", nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="RUB", nullable=False)

    service_percent_default: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shift_type_default: Mapped[str] = mapped_column(String(20), default="fixed", nullable=False)
    pay_for_shift_default: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[int] = mapped_column(BigInteger, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=utc_ts, onupdate=utc_ts, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="workplaces",
        foreign_keys=[user_id],
    )

    halls: Mapped[List["Hall"]] = relationship(
        "Hall",
        back_populates="workplace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    menu_categories: Mapped[List["MenuCategory"]] = relationship(
        "MenuCategory",
        back_populates="workplace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    shifts: Mapped[List["Shift"]] = relationship(
        "Shift",
        back_populates="workplace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    notes: Mapped[List["Notes"]] = relationship(
        "Notes",
        back_populates="workplace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Shift(Base):
    __tablename__ = "shifts"

    __table_args__ = (
        # Fast lookup of open shift by workplace
        Index("ix_shifts_workplace_open", "workplace_id", "is_closed"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    workplace_id: Mapped[str] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    start_time: Mapped[int] = mapped_column(Integer, default=utc_ts, nullable=False)

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    end_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # snapshot on shift start
    place_work_title: Mapped[str] = mapped_column(String(255), default="Waiter Note", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    service_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shift_type: Mapped[str] = mapped_column(String(20), default="fixed", nullable=False)
    pay_for_shift: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    # aggregates
    total_pay_for_shift: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)
    total_tips: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)
    total_cash_register: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    workplace: Mapped["Workplace"] = relationship("Workplace", back_populates="shifts")

    orders: Mapped[List["Order"]] = relationship(
        "Order",
        back_populates="shift",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    notes: Mapped[List["Notes"]] = relationship(
        "Notes",
        back_populates="shift",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Order(Base):
    __tablename__ = "orders"

    __table_args__ = (
        Index("ix_orders_shift_created", "shift_id", "created_at"),
        Index("ix_orders_shift_active", "shift_id", "is_paid"),  # active orders
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    shift_id: Mapped[str] = mapped_column(
        ForeignKey("shifts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    hall_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("halls.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    table_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("tables.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # snapshots at order creation (for history / denormalization)
    table_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hall_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[int] = mapped_column(Integer, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=utc_ts, onupdate=utc_ts, nullable=False)

    closed_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    tips: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)
    total_price: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    # Source of truth: paid -> order closed
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    shift: Mapped["Shift"] = relationship("Shift", back_populates="orders")

    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    menu_item_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("menu_items.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    price: Mapped[float] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_price: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="items")

    # optional helper (read-only join to menu)
    menu_item: Mapped[Optional["MenuItem"]] = relationship(
        "MenuItem",
        foreign_keys=[menu_item_id],
        viewonly=True,
    )


class Notes(Base):
    __tablename__ = "notes"

    __table_args__ = (
        CheckConstraint(
            """
            (
              scope = 'global'
              AND workplace_id IS NULL
              AND shift_id IS NULL
            )
            OR
            (
              scope = 'workplace'
              AND workplace_id IS NOT NULL
              AND shift_id IS NULL
            )
            OR
            (
              scope = 'shift'
              AND shift_id IS NOT NULL
            )
            """,
            name="ck_notes_scope_consistency",
        ),
        Index("ix_notes_user_updated", "user_id", "updated_at"),
        Index("ix_notes_user_scope", "user_id", "scope"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    scope: Mapped[str] = mapped_column(
        default="global",
        nullable=False,
        index=True,
    )

    workplace_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    shift_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("shifts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    header: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[int] = mapped_column(Integer, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=utc_ts, onupdate=utc_ts, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="notes")
    workplace: Mapped[Optional["Workplace"]] = relationship("Workplace", back_populates="notes")
    shift: Mapped[Optional["Shift"]] = relationship("Shift", back_populates="notes")


class Hall(Base):
    __tablename__ = "halls"

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    workplace_id: Mapped[str] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    width: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    scale: Mapped[float] = mapped_column(SCALE, default=1.0, nullable=False)

    workplace: Mapped["Workplace"] = relationship("Workplace", back_populates="halls")

    tables: Mapped[List["Table"]] = relationship(
        "Table",
        back_populates="hall",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Table(Base):
    __tablename__ = "tables"

    # Table.order_id is a UI cache. Source of truth is Order.table_id.
    __table_args__ = (
        UniqueConstraint("hall_id", "number", name="uq_tables_hall_number"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    hall_id: Mapped[str] = mapped_column(
        ForeignKey("halls.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    order_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False)

    x: Mapped[float] = mapped_column(COORD, default=0, nullable=False)
    y: Mapped[float] = mapped_column(COORD, default=0, nullable=False)

    width: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    rotation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    border_radius: Mapped[int] = mapped_column(Integer, default=15, nullable=False)

    status: Mapped[str] = mapped_column(TableStatus, default="free", nullable=False)

    hall: Mapped["Hall"] = relationship("Hall", back_populates="tables")


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    __table_args__ = (
        Index("ix_menu_categories_workplace_active_pos", "workplace_id", "is_active", "position"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    workplace_id: Mapped[str] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    workplace: Mapped["Workplace"] = relationship("Workplace", back_populates="menu_categories")

    items: Mapped[List["MenuItem"]] = relationship(
        "MenuItem",
        back_populates="category",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MenuItem(Base):
    __tablename__ = "menu_items"

    __table_args__ = (
        Index("ix_menu_items_category_active_pos", "category_id", "is_active", "position"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    category_id: Mapped[str] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    portion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    price: Mapped[float] = mapped_column(MONEY, nullable=False)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category: Mapped["MenuCategory"] = relationship("MenuCategory", back_populates="items")


# =========================
# DB Init
# =========================

async def init_db():
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all)  # осторожно
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Tables created successfully")

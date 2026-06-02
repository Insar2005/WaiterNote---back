from __future__ import annotations

import enum
import os
import ssl
from pathlib import Path
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
    text,
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

# Unified timestamp type: BigInteger everywhere (safe past 2038)
TS = BigInteger


# =========================
# DB Connection
# =========================

# === Подключение к БД ===
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in os.environ and os.environ.get(key):
                continue
            value = value.strip().strip('"').strip("'")
            os.environ[key] = value
    except OSError:
        return


_load_dotenv()


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _build_ssl_context() -> ssl.SSLContext | None:
    if _bool_env("DB_SSL_DISABLE"):
        return None

    # DB_SSL_INSECURE: encrypt the connection but skip certificate
    # verification. Needed for managed Postgres providers whose CA
    # certificates don't satisfy modern OpenSSL's strict checks
    # (e.g. "Missing Authority Key Identifier" on Python 3.13).
    # The traffic is still TLS-encrypted; only the authenticity check
    # of the server certificate is relaxed.
    if _bool_env("DB_SSL_INSECURE"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        print("[db] SSL enabled WITHOUT certificate verification (DB_SSL_INSECURE)")
        return ctx

    # Resolve a CA bundle path: explicit env var first, then a bundled
    # default next to this file. Crucially we verify the file actually
    # exists before handing it to ssl — passing a missing path to
    # create_default_context(cafile=...) raises FileNotFoundError and
    # crashes the whole app at import time (e.g. in a container where
    # the cert wasn't shipped).
    ca_path = os.getenv("DB_SSL_CA") or ""
    if ca_path and not Path(ca_path).is_file():
        print(f"[db] DB_SSL_CA points to a missing file: {ca_path} — ignoring")
        ca_path = ""

    if not ca_path:
        default_ca = Path(__file__).resolve().parent / ".cloud_cert" / "ca.crt"
        if default_ca.is_file():
            ca_path = str(default_ca)

    if ca_path:
        return ssl.create_default_context(cafile=ca_path)

    # No custom CA available — fall back to the system trust store.
    # This still validates the server certificate against public CAs.
    return ssl.create_default_context()


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# Normalise the URL scheme for SQLAlchemy's async engine. Many managed
# Postgres providers (Railway, Render, Heroku) expose DATABASE_URL with
# the bare `postgresql://` scheme, but SQLAlchemy's async engine needs
# the driver-qualified form `postgresql+asyncpg://`. We patch it here
# rather than relying on the user to remember the right prefix in every
# environment.
if DATABASE_URL.startswith("postgres://"):
    # Older convention some platforms still use.
    DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL[len("postgresql://"):]
# If it already has `postgresql+asyncpg://`, leave it alone.

ssl_context = _build_ssl_context()

# connect_args is passed straight to asyncpg.connect().
#   ssl              — TLS context (or omitted entirely)
#   timeout          — cap on establishing a new connection (seconds)
#   command_timeout  — cap on any single query; without it a stalled
#                      query hangs until the HTTP-level timeout fires,
#                      which surfaces to the client as "Сеть недоступна".
connect_args: dict = {
    "timeout": 10,
    "command_timeout": 10,
}
if ssl_context is not None:
    connect_args["ssl"] = ssl_context

engine = create_async_engine(
    url=DATABASE_URL,
    connect_args=connect_args,
    echo=_bool_env("SQLALCHEMY_ECHO"),
    pool_recycle=1800,
    # Validate a pooled connection before handing it out. Without this a
    # connection that died while idle (network blip between the app and
    # the managed DB) is reused, and the next query hangs. pre_ping turns
    # that into a quick reconnect instead of a stall.
    pool_pre_ping=True,
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

ShiftTypeEnum = SAEnum(
    "fixed",
    "percent",
    name="shift_type",
)


class NoteScope(str, enum.Enum):
    global_ = "global"
    workplace = "workplace"
    shift = "shift"


NoteScopeEnum = SAEnum(
    NoteScope,
    name="note_scope",
    values_callable=lambda e: [m.value for m in e],
)


class WorkplaceRole(str, enum.Enum):
    owner = "owner"
    member = "member"


WorkplaceRoleEnum = SAEnum(
    WorkplaceRole,
    name="workplace_role",
    values_callable=lambda e: [m.value for m in e],
)


# =========================
# Base
# =========================

class Base(AsyncAttrs, DeclarativeBase):
    pass


# =========================
# User
# =========================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    language: Mapped[str] = mapped_column(String(10), default="ru", nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow", nullable=False)

    last_online_at: Mapped[Optional[int]] = mapped_column(TS, nullable=True, index=True)

    last_workplace_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workplaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    is_onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # === Appearance preferences ===
    # Cross-device sync of theme + accent. Stored as short string keys
    # so backend doesn't need to know the actual colors — the frontend
    # has the canonical accent palette. Free-form String (not Enum) so
    # adding a new accent doesn't require a DB migration.
    accent_key: Mapped[str] = mapped_column(String(32), default="green", nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)

    created_at: Mapped[int] = mapped_column(TS, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(TS, default=utc_ts, onupdate=utc_ts, nullable=False)

    # Relationships
    owned_workplaces: Mapped[List["Workplace"]] = relationship(
        "Workplace",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="Workplace.owner_id",
    )

    memberships: Mapped[List["WorkplaceMember"]] = relationship(
        "WorkplaceMember",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="WorkplaceMember.user_id",
    )

    notes: Mapped[List["Notes"]] = relationship(
        "Notes",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# =========================
# Workplace
# =========================

class Workplace(Base):
    __tablename__ = "workplaces"

    __table_args__ = (
        CheckConstraint(
            "service_percent_default >= 0 AND service_percent_default <= 100",
            name="ck_workplaces_service_percent_range",
        ),
        Index("ix_workplaces_owner_position", "owner_id", "position"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    # renamed from user_id -> owner_id (semantic clarity for future sharing)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(255), default="Waiter Note", nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="Europe/Moscow", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="RUB", nullable=False)

    service_percent_default: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shift_type_default: Mapped[str] = mapped_column(ShiftTypeEnum, default="fixed", nullable=False)
    pay_for_shift_default: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[int] = mapped_column(TS, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(TS, default=utc_ts, onupdate=utc_ts, nullable=False)

    # Relationships
    owner: Mapped["User"] = relationship(
        "User",
        back_populates="owned_workplaces",
        foreign_keys=[owner_id],
    )

    members: Mapped[List["WorkplaceMember"]] = relationship(
        "WorkplaceMember",
        back_populates="workplace",
        cascade="all, delete-orphan",
        passive_deletes=True,
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


# =========================
# WorkplaceMember (shared access)
# =========================

class WorkplaceMember(Base):
    """
    Membership table for shared workplaces.
    Owner is ALSO stored here with role='owner' (created implicitly on workplace create).
    This lets us query "all workplaces user can access" with one join.
    """
    __tablename__ = "workplace_members"

    __table_args__ = (
        UniqueConstraint("workplace_id", "user_id", name="uq_workplace_members"),
        Index("ix_workplace_members_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    workplace_id: Mapped[str] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(WorkplaceRoleEnum, default="member", nullable=False)

    # for "last active workplace" tracking per user
    joined_at: Mapped[int] = mapped_column(TS, default=utc_ts, nullable=False)

    workplace: Mapped["Workplace"] = relationship("Workplace", back_populates="members")
    user: Mapped["User"] = relationship(
        "User",
        back_populates="memberships",
        foreign_keys=[user_id],
    )


# =========================
# Shift
# =========================

class Shift(Base):
    __tablename__ = "shifts"

    __table_args__ = (
        Index("ix_shifts_workplace_open", "workplace_id", "is_closed"),
        # NULL end_time = open shift; allows efficient "find open shift" query
        Index("ix_shifts_workplace_end", "workplace_id", "end_time"),
        # Enforce: at most one open shift per (workplace, user).
        # Postgres partial unique index — only applies to rows where end_time IS NULL.
        Index(
            "uq_shifts_open_per_user",
            "workplace_id",
            "opened_by_user_id",
            unique=True,
            postgresql_where=text("end_time IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    workplace_id: Mapped[str] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Who opened this shift (important for shared workplaces)
    opened_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    start_time: Mapped[int] = mapped_column(TS, default=utc_ts, nullable=False)

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # NULL instead of 0 — idiomatic "not closed yet"
    end_time: Mapped[Optional[int]] = mapped_column(TS, nullable=True)

    # snapshot on shift start (no default — must be set by service layer from Workplace)
    place_work_title: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    service_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    shift_type: Mapped[str] = mapped_column(ShiftTypeEnum, nullable=False)
    pay_for_shift: Mapped[float] = mapped_column(MONEY, nullable=False)

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


# =========================
# Order
# =========================

class Order(Base):
    __tablename__ = "orders"

    __table_args__ = (
        Index("ix_orders_shift_created", "shift_id", "created_at"),
        Index("ix_orders_shift_active", "shift_id", "is_paid"),
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

    # snapshots at order creation (survive table/hall deletion)
    table_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hall_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[int] = mapped_column(TS, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(TS, default=utc_ts, onupdate=utc_ts, nullable=False)

    # NULL = not closed yet
    closed_at: Mapped[Optional[int]] = mapped_column(TS, nullable=True)

    tips: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)
    total_price: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    shift: Mapped["Shift"] = relationship("Shift", back_populates="orders")

    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# =========================
# OrderItem
# =========================

class OrderItem(Base):
    __tablename__ = "order_items"

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("price >= 0", name="ck_order_items_price_nonnegative"),
    )

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
    # kept as physical column (not GENERATED) for cross-DB portability;
    # service layer is responsible for keeping it = price * quantity
    total_price: Mapped[float] = mapped_column(MONEY, default=0, nullable=False)

    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # True when the waiter has physically brought this item to the table.
    # Helps trace progress on multi-item orders ("3/5 поданo").
    # Defaults to False on creation; toggled via PATCH /orders/order-items/{id}.
    served: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")

    menu_item: Mapped[Optional["MenuItem"]] = relationship(
        "MenuItem",
        foreign_keys=[menu_item_id],
        viewonly=True,
    )


# =========================
# Notes
# =========================

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
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Proper enum now
    scope: Mapped[str] = mapped_column(
        NoteScopeEnum,
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
    # renamed for consistency with other models (*_active, is_*)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[int] = mapped_column(TS, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(TS, default=utc_ts, onupdate=utc_ts, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="notes")
    workplace: Mapped[Optional["Workplace"]] = relationship("Workplace", back_populates="notes")
    shift: Mapped[Optional["Shift"]] = relationship("Shift", back_populates="notes")


# =========================
# Hall
# =========================

class Hall(Base):
    __tablename__ = "halls"

    __table_args__ = (
        Index("ix_halls_workplace_position", "workplace_id", "position"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    workplace_id: Mapped[str] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    width: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    scale: Mapped[float] = mapped_column(SCALE, default=1.0, nullable=False)

    workplace: Mapped["Workplace"] = relationship("Workplace", back_populates="halls")

    tables: Mapped[List["Table"]] = relationship(
        "Table",
        back_populates="hall",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    layouts: Mapped[List["HallLayout"]] = relationship(
        "HallLayout",
        back_populates="hall",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# =========================
# Hall Layout (saved arrangement template)
# =========================

class HallLayout(Base):
    """
    A saved snapshot of table positions within a hall. Lets the user
    switch between named arrangements (e.g. "Стандарт" / "Банкет")
    without recreating tables. Positions reference tables by their
    `number` (stable across rearrangements) rather than database id.
    """
    __tablename__ = "hall_layouts"

    __table_args__ = (
        Index("ix_hall_layouts_hall", "hall_id"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    hall_id: Mapped[str] = mapped_column(
        ForeignKey("halls.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[int] = mapped_column(Integer, default=utc_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=utc_ts, onupdate=utc_ts, nullable=False)

    hall: Mapped["Hall"] = relationship("Hall", back_populates="layouts")

    positions: Mapped[List["TablePosition"]] = relationship(
        "TablePosition",
        back_populates="layout",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TablePosition(Base):
    """
    Where a specific table number should be placed when applying a given
    layout. Identified by `table_number` (not table_id) so applying a
    layout to a hall whose tables were recreated still finds the right slot.
    """
    __tablename__ = "table_positions"

    __table_args__ = (
        UniqueConstraint("layout_id", "table_number", name="uq_table_positions_layout_number"),
        Index("ix_table_positions_layout", "layout_id"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    layout_id: Mapped[str] = mapped_column(
        ForeignKey("hall_layouts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    table_number: Mapped[int] = mapped_column(Integer, nullable=False)

    x: Mapped[float] = mapped_column(COORD, default=0, nullable=False)
    y: Mapped[float] = mapped_column(COORD, default=0, nullable=False)

    width: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    rotation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    border_radius: Mapped[int] = mapped_column(Integer, default=15, nullable=False)

    layout: Mapped["HallLayout"] = relationship("HallLayout", back_populates="positions")


# =========================
# Table
# =========================

class Table(Base):
    __tablename__ = "tables"

    # Table.order_id is a UI cache. Source of truth is Order.table_id.
    # Service layer MUST update both sides in a single transaction
    # (see services/orders.py: attach_order_to_table / detach_order).
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


# =========================
# Menu
# =========================

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
        CheckConstraint("price >= 0", name="ck_menu_items_price_nonnegative"),
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
# ImportShare (one-time publish window for importing a workplace's content)
# =========================

class ImportShare(Base):
    """
    A time-limited public publication of a workplace's halls/menu/layouts.

    The owner creates one of these to grant temporary read-and-copy access
    to anyone who has the `code`. The link/code is meant to be shared
    out-of-band (in chat, voice, message) — anyone with it can preview and
    import while the share is active. This is NOT a one-shot ticket; the
    same code can be used by many people in parallel during its TTL.

    Active window: revoked_at IS NULL AND expires_at > now()

    The shared user-facing string is `code` (~8 chars from a friendly
    alphabet). `id` is a normal nanoid PK to keep DB joins fast and to
    avoid leaking the code into log lines or admin UIs.
    """
    __tablename__ = "import_shares"

    __table_args__ = (
        Index("ix_import_shares_code", "code", unique=True),
        Index("ix_import_shares_workplace", "workplace_id"),
        Index("ix_import_shares_active", "expires_at", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(ID21, primary_key=True)

    # Short, friendly, case-insensitive (we store uppercase). Unique across
    # the whole system so the bare code is enough to find the share — no
    # workplace_id needed in the URL.
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)

    workplace_id: Mapped[str] = mapped_column(
        ForeignKey("workplaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    created_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # unix seconds. expires_at is set on creation = now + ttl_hours*3600
    created_at: Mapped[int] = mapped_column(TS, default=utc_ts, nullable=False)
    expires_at: Mapped[int] = mapped_column(TS, nullable=False)

    # NULL until the owner explicitly closes the share before its TTL.
    revoked_at: Mapped[Optional[int]] = mapped_column(TS, nullable=True)

    # Bumped by every successful POST /import/{code}/apply.
    # Lets the owner see "8 people imported using this link" at a glance.
    import_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    workplace: Mapped["Workplace"] = relationship("Workplace")


# =========================
# DB Init
# =========================

async def init_db():
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all)  # осторожно
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Tables created successfully")
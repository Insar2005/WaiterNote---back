"""Waiter Note API (MVP).

Backend goals for this iteration (per product requirements):

1) Profile
   - Front sends: tg_id
   - Back returns: User data + Notes + list of workplaces (id/title)

2) Workplace context
   - Front sends: workplace_id (usually user.last_workplace_id)
   - Back returns: workplace expanded (halls+tables, menu categories+items, shifts, workplace notes)

3) CRUD (GET/POST/PATCH)
   - Shifts
   - Orders (+ order items)
   - Halls and tables
   - Menu (categories & items)

This file is written for FastAPI + SQLAlchemy Async.
"""

from __future__ import annotations

import secrets
import string
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from models import (
    Hall,
    MenuCategory,
    MenuItem,
    Notes,
    Order,
    OrderItem,
    Shift,
    Table,
    User,
    Workplace,
    async_session,
    engine,
    init_db,
    utc_ts,
)


# =========================
# Helpers
# =========================

def gen_id(prefix: str) -> str:
    """Generate an ID that fits models.ID21 (String(21)).

    Project uses IDs like:
      - WPL_00000000000000001  (len(prefix_with_underscore)=4  -> 17 digits)
      - HALL_0000000000000001  (len(prefix_with_underscore)=5  -> 16 digits)

    We therefore compute suffix length dynamically to keep total length == 21.
    """

    if not prefix:
        raise ValueError("prefix must be non-empty")
    p = prefix.upper().rstrip("_")
    if not p.isalnum():
        raise ValueError("prefix must be alphanumeric")

    prefix_with_sep = f"{p}_"
    digits_len = 21 - len(prefix_with_sep)
    if digits_len <= 0:
        raise ValueError("prefix is too long for ID21")

    suffix = "".join(secrets.choice(string.digits) for _ in range(digits_len))
    return f"{prefix_with_sep}{suffix}"


async def _get_user_by_tg_id(session, tg_id: int) -> User:
    res = await session.execute(
        select(User)
        .options(selectinload(User.workplaces), selectinload(User.notes))
        .where(User.tg_id == tg_id)
    )
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _get_workplace_expanded(session, workplace_id: str) -> Workplace:
    res = await session.execute(
        select(Workplace)
        .options(
            selectinload(Workplace.halls).selectinload(Hall.tables),
            selectinload(Workplace.menu_categories).selectinload(MenuCategory.items),
            selectinload(Workplace.shifts),
            selectinload(Workplace.notes),
        )
        .where(Workplace.id == workplace_id)
    )
    workplace = res.scalars().first()
    if not workplace:
        raise HTTPException(status_code=404, detail="Workplace not found")
    return workplace


async def _get_shift_expanded(session, shift_id: str) -> Shift:
    res = await session.execute(
        select(Shift)
        .options(selectinload(Shift.orders).selectinload(Order.items))
        .where(Shift.id == shift_id)
    )
    shift = res.scalars().first()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    return shift


async def _recalc_shift_aggregates(session, shift_id: str) -> None:
    """Best-effort recalculation of shift aggregates.

    This is intentionally minimal (MVP):
    - order_count
    - total_tips
    - total_cash_register
    - duration (if shift closed)
    """
    shift = await session.get(Shift, shift_id)
    if not shift:
        return
    res = await session.execute(select(Order).where(Order.shift_id == shift_id))
    orders = list(res.scalars().all())

    shift.order_count = len(orders)
    shift.total_tips = float(sum((o.tips or 0) for o in orders))
    shift.total_cash_register = float(sum((o.total_price or 0) for o in orders if o.is_paid))
    if shift.is_closed and shift.end_time and shift.end_time >= shift.start_time:
        shift.duration = int(shift.end_time - shift.start_time)


async def _next_workplace_position(session, user_id: int) -> int:
    """Compute next workplace position for a given user."""
    last_pos = await session.scalar(
        select(Workplace.position)
        .where(Workplace.user_id == user_id)
        .order_by(Workplace.position.desc())
        .limit(1)
    )
    return int(last_pos + 1) if last_pos is not None else 0


async def _create_workplace(
    session,
    *,
    user_id: int,
    title: str,
    timezone: str,
    currency: str,
    service_percent_default: int,
    shift_type_default: str,
    pay_for_shift_default: float,
    position: Optional[int] = None,
    workplace_id: Optional[str] = None,
) -> Workplace:
    """Create a workplace for a user (does not commit)."""
    pos = position if position is not None else await _next_workplace_position(session, user_id)

    wp = Workplace(
        id=workplace_id or gen_id("WPL"),
        user_id=user_id,
        title=title,
        timezone=timezone,
        currency=currency,
        service_percent_default=int(service_percent_default),
        shift_type_default=shift_type_default,
        pay_for_shift_default=float(pay_for_shift_default),
        position=int(pos),
        is_archived=False,
    )
    session.add(wp)
    await session.flush()  # make wp.id available
    return wp


async def _create_first_hall(
    session,
    *,
    workplace_id: str,
    name: str = "Основной зал",
    width: int = 1000,
    height: int = 600,
    scale: float = 1.0,
    hall_id: Optional[str] = None,
) -> Hall:
    """Create the first hall for a workplace (does not commit)."""
    hall = Hall(
        id=hall_id or gen_id("HALL"),
        workplace_id=workplace_id,
        name=name,
        position=0,
        width=int(width),
        height=int(height),
        scale=float(scale),
    )
    session.add(hall)
    await session.flush()
    return hall

# =========================
# Pydantic Schemas
# =========================


class _BaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class WorkplaceLiteOut(_BaseOut):
    id: str
    title: str


class UserOut(_BaseOut):
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


class NoteOut(_BaseOut):
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


class ProfileResponse(BaseModel):
    user: UserOut
    notes: List[NoteOut]
    workplaces: List[WorkplaceLiteOut]


class TableOut(_BaseOut):
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


class HallOut(_BaseOut):
    id: str
    workplace_id: str
    name: str
    position: int
    width: int
    height: int
    scale: float
    tables: List[TableOut] = Field(default_factory=list)


class MenuItemOut(_BaseOut):
    id: str
    category_id: str
    title: str
    description: Optional[str] = None
    portion: Optional[str] = None
    price: float
    position: int
    is_active: bool


class MenuCategoryOut(_BaseOut):
    id: str
    workplace_id: str
    title: str
    position: int
    is_active: bool
    items: List[MenuItemOut] = Field(default_factory=list)


class ShiftOut(_BaseOut):
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


class OrderItemOut(_BaseOut):
    id: str
    order_id: str
    menu_item_id: Optional[str] = None
    title: str
    price: float
    quantity: int
    total_price: float
    comment: Optional[str] = None


class OrderOut(_BaseOut):
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
    items: List[OrderItemOut] = Field(default_factory=list)


class WorkplaceOut(_BaseOut):
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


class WorkplaceExpandedResponse(WorkplaceOut):
    halls: List[HallOut] = Field(default_factory=list)
    menu_categories: List[MenuCategoryOut] = Field(default_factory=list)
    shifts: List[ShiftOut] = Field(default_factory=list)
    notes: List[NoteOut] = Field(default_factory=list)


# =========================
# Request Schemas
# =========================


class UserCreateRequest(BaseModel):
    id:int
    tg_id: int
    username: Optional[str] = None

    # user defaults
    language: str = "ru"
    timezone: str = "Europe/Moscow"
    last_online_at: Optional[int] = None
    is_onboarding_completed: bool = False
    is_disabled: bool = False

    # initial workplace defaults
    workplace_title: str = "Waiter Note"
    currency: str = "RUB"
    service_percent_default: int = Field(default=0, ge=0, le=100)
    shift_type_default: str = "fixed"
    pay_for_shift_default: float = 0

    # initial hall defaults
    create_default_hall: bool = True
    default_hall_name: str = "Основной зал"
    hall_width: int = 1000
    hall_height: int = 600
    hall_scale: float = 1.0


class WorkplaceCreateRequest(BaseModel):
    id: Optional[str] = None
    title: str = "Waiter Note"
    timezone: Optional[str] = None
    currency: str = "RUB"
    service_percent_default: int = Field(default=0, ge=0, le=100)
    shift_type_default: str = "fixed"
    pay_for_shift_default: float = 0
    position: Optional[int] = None

    # behavior
    make_last: bool = True

    # hall defaults
    create_default_hall: bool = True
    default_hall_name: str = "Основной зал"
    hall_width: int = 1000
    hall_height: int = 600
    hall_scale: float = 1.0


class UserPatchRequest(BaseModel):
    username: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    last_online_at: Optional[int] = None
    last_workplace_id: Optional[str] = None
    is_onboarding_completed: Optional[bool] = None
    is_disabled: Optional[bool] = None


class HallCreateRequest(BaseModel):
    id: Optional[str] = None
    name: str
    position: int = 0
    width: int = 1000
    height: int = 600
    scale: float = 1.0


class HallPatchRequest(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    scale: Optional[float] = None


class TableCreateRequest(BaseModel):
    id: Optional[str] = None
    number: int
    x: float = 0
    y: float = 0
    width: int = 100
    height: int = 100
    rotation: int = 0
    border_radius: int = 15
    status: str = "free"


class TablePatchRequest(BaseModel):
    order_id: Optional[str] = None
    number: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    rotation: Optional[int] = None
    border_radius: Optional[int] = None
    status: Optional[str] = None


class MenuCategoryCreateRequest(BaseModel):
    id: Optional[str] = None
    title: str
    position: int = 0
    is_active: bool = True


class MenuCategoryPatchRequest(BaseModel):
    title: Optional[str] = None
    position: Optional[int] = None
    is_active: Optional[bool] = None


class MenuItemCreateRequest(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    portion: Optional[str] = None
    price: float
    position: int = 0
    is_active: bool = True


class MenuItemPatchRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    portion: Optional[str] = None
    price: Optional[float] = None
    position: Optional[int] = None
    is_active: Optional[bool] = None


class ShiftCreateRequest(BaseModel):
    id: Optional[str] = None
    start_time: Optional[int] = None
    # overrides (optional)
    service_percent: Optional[int] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None


class ShiftPatchRequest(BaseModel):
    is_closed: Optional[bool] = None
    end_time: Optional[int] = None
    service_percent: Optional[int] = None
    shift_type: Optional[str] = None
    pay_for_shift: Optional[float] = None


class OrderItemCreateRequest(BaseModel):
    id: Optional[str] = None
    menu_item_id: Optional[str] = None
    title: str
    price: float
    quantity: int = 1
    comment: Optional[str] = None


class OrderCreateRequest(BaseModel):
    id: Optional[str] = None
    hall_id: Optional[str] = None
    table_id: Optional[str] = None
    comments: Optional[str] = None
    tips: float = 0
    total_price: float = 0
    items: List[OrderItemCreateRequest] = Field(default_factory=list)


class OrderPatchRequest(BaseModel):
    hall_id: Optional[str] = None
    table_id: Optional[str] = None
    comments: Optional[str] = None
    tips: Optional[float] = None
    total_price: Optional[float] = None
    is_paid: Optional[bool] = None
    is_done: Optional[bool] = None
    closed_at: Optional[int] = None


class OrderItemPatchRequest(BaseModel):
    menu_item_id: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    comment: Optional[str] = None


# =========================
# FastAPI app
# =========================


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="Waiter Note API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://waiterapp-cc1e8.web.app",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Routers
# =========================


users_router = APIRouter(prefix="/api/users", tags=["users"])
workplaces_router = APIRouter(prefix="/api/workplaces", tags=["workplaces"])
hall_router = APIRouter(prefix="/api", tags=["halls"])
menu_router = APIRouter(prefix="/api", tags=["menu"])
shifts_router = APIRouter(prefix="/api", tags=["shifts"])
orders_router = APIRouter(prefix="/api", tags=["orders"])


# -------------------------
# Profile / User
# -------------------------


@users_router.post("", response_model=ProfileResponse)
async def create_user(payload: UserCreateRequest, response: Response):
    """Create user (by tg_id) and bootstrap first workplace + first hall.

    If user already exists, returns existing profile payload (idempotent).
    """
    async with async_session() as session:
        # Fast path: already exists
        existing = await session.scalar(select(User).where(User.tg_id == payload.tg_id))
        if existing:
            response.status_code = 200
            user = await _get_user_by_tg_id(session, payload.tg_id)
            workplaces_sorted = sorted(user.workplaces, key=lambda w: (w.position, w.created_at))
            notes_sorted = sorted(user.notes, key=lambda n: n.updated_at, reverse=True)
            return ProfileResponse(
                user=UserOut.model_validate(user),
                notes=[NoteOut.model_validate(n) for n in notes_sorted],
                workplaces=[WorkplaceLiteOut.model_validate(w) for w in workplaces_sorted],
            )

        response.status_code = 201

        user = User(
           id=payload.id,
            tg_id=payload.tg_id,
            username=payload.username,
            language=payload.language,
            timezone=payload.timezone,
            last_online_at=payload.last_online_at,
            is_onboarding_completed=bool(payload.is_onboarding_completed),
            is_disabled=bool(payload.is_disabled),
        )
        session.add(user)

        try:
            await session.flush()  # user.id assigned

            wp = await _create_workplace(
                session,
                user_id=user.id,
                title=payload.workplace_title,
                timezone=payload.timezone,
                currency=payload.currency,
                service_percent_default=payload.service_percent_default,
                shift_type_default=payload.shift_type_default,
                pay_for_shift_default=payload.pay_for_shift_default,
            )

            # Make it active
            user.last_workplace_id = wp.id

            # Create initial hall
            if payload.create_default_hall:
                await _create_first_hall(
                    session,
                    workplace_id=wp.id,
                    name=payload.default_hall_name,
                    width=payload.hall_width,
                    height=payload.hall_height,
                    scale=payload.hall_scale,
                )

            await session.commit()
        except IntegrityError:
            # If a concurrent request created the user/workplace first
            await session.rollback()
            response.status_code = 200
        except Exception:
            await session.rollback()
            raise

        user = await _get_user_by_tg_id(session, payload.tg_id)
        workplaces_sorted = sorted(user.workplaces, key=lambda w: (w.position, w.created_at))
        notes_sorted = sorted(user.notes, key=lambda n: n.updated_at, reverse=True)
        return ProfileResponse(
            user=UserOut.model_validate(user),
            notes=[NoteOut.model_validate(n) for n in notes_sorted],
            workplaces=[WorkplaceLiteOut.model_validate(w) for w in workplaces_sorted],
        )


@users_router.post("/{tg_id}/workplaces", response_model=WorkplaceOut)
async def create_workplace_for_user(tg_id: int, payload: WorkplaceCreateRequest, response: Response):
    """Create a workplace for an existing user (+ optional default hall).

    Returns created workplace.
    """
    async with async_session() as session:
        user = await _get_user_by_tg_id(session, tg_id)

        # If timezone not passed, inherit from user
        tz = payload.timezone or user.timezone

        wp = await _create_workplace(
            session,
            user_id=user.id,
            title=payload.title,
            timezone=tz,
            currency=payload.currency,
            service_percent_default=payload.service_percent_default,
            shift_type_default=payload.shift_type_default,
            pay_for_shift_default=payload.pay_for_shift_default,
            position=payload.position,
            workplace_id=payload.id,
        )

        if payload.create_default_hall:
            await _create_first_hall(
                session,
                workplace_id=wp.id,
                name=payload.default_hall_name,
                width=payload.hall_width,
                height=payload.hall_height,
                scale=payload.hall_scale,
            )

        if payload.make_last:
            user.last_workplace_id = wp.id

        await session.commit()
        await session.refresh(wp)

        response.status_code = 201
        return WorkplaceOut.model_validate(wp)

@users_router.get("/{tg_id}/profile", response_model=ProfileResponse)
async def get_profile(tg_id: int):
    """Profile bootstrap.

    Front sends: tg_id
    Back returns: user + notes + workplaces (id/title)
    """
    async with async_session() as session:
        user = await _get_user_by_tg_id(session, tg_id)

        # sort workplaces by position (stable UI)
        workplaces_sorted = sorted(user.workplaces, key=lambda w: (w.position, w.created_at))
        # notes by updated_at desc
        notes_sorted = sorted(user.notes, key=lambda n: n.updated_at, reverse=True)

        return ProfileResponse(
            user=UserOut.model_validate(user),
            notes=[NoteOut.model_validate(n) for n in notes_sorted],
            workplaces=[WorkplaceLiteOut.model_validate(w) for w in workplaces_sorted],
        )


@users_router.patch("/{tg_id}", response_model=UserOut)
async def patch_user(tg_id: int, patch: UserPatchRequest):
    """Patch user fields (including last_workplace_id)."""
    async with async_session() as session:
        user = await _get_user_by_tg_id(session, tg_id)
        data = patch.model_dump(exclude_unset=True)

        # validate last_workplace_id ownership
        if "last_workplace_id" in data and data["last_workplace_id"] is not None:
            wp_ids = {w.id for w in user.workplaces}
            if data["last_workplace_id"] not in wp_ids:
                raise HTTPException(status_code=400, detail="last_workplace_id does not belong to this user")

        for k, v in data.items():
            setattr(user, k, v)

        await session.commit()
        await session.refresh(user)
        return UserOut.model_validate(user)


# -------------------------
# Workplace (expanded)
# -------------------------


@workplaces_router.get("/{workplace_id}/expanded", response_model=WorkplaceExpandedResponse)
async def get_workplace_expanded(workplace_id: str):
    """Workplace context payload.

    Used on profile workplace switch and on app boot (by user.last_workplace_id).
    """
    async with async_session() as session:
        workplace = await _get_workplace_expanded(session, workplace_id)

        # Sort nested lists for stable UI
        workplace.halls.sort(key=lambda h: h.position)
        for h in workplace.halls:
            h.tables.sort(key=lambda t: t.number)
        workplace.menu_categories.sort(key=lambda c: c.position)
        for c in workplace.menu_categories:
            c.items.sort(key=lambda i: i.position)
        workplace.shifts.sort(key=lambda s: s.start_time, reverse=True)
        workplace.notes.sort(key=lambda n: n.updated_at, reverse=True)

        return WorkplaceExpandedResponse.model_validate(workplace)


# -------------------------
# Halls
# -------------------------


@hall_router.get("/workplaces/{workplace_id}/halls", response_model=List[HallOut])
async def list_halls(workplace_id: str):
    async with async_session() as session:
        res = await session.execute(
            select(Hall)
            .options(selectinload(Hall.tables))
            .where(Hall.workplace_id == workplace_id)
        )
        halls = list(res.scalars().all())
        halls.sort(key=lambda h: h.position)
        for h in halls:
            h.tables.sort(key=lambda t: t.number)
        return [HallOut.model_validate(h) for h in halls]


@hall_router.post("/workplaces/{workplace_id}/halls", response_model=HallOut)
async def create_hall(workplace_id: str, payload: HallCreateRequest):
    async with async_session() as session:
        # ensure workplace exists
        wp = await session.get(Workplace, workplace_id)
        if not wp:
            raise HTTPException(status_code=404, detail="Workplace not found")

        hall = Hall(
            id=payload.id or gen_id("HALL"),
            workplace_id=workplace_id,
            name=payload.name,
            position=payload.position,
            width=payload.width,
            height=payload.height,
            scale=payload.scale,
        )

        session.add(hall)
        await session.commit()
        await session.refresh(hall)
        return HallOut.model_validate(hall)


@hall_router.patch("/halls/{hall_id}", response_model=HallOut)
async def patch_hall(hall_id: str, patch: HallPatchRequest):
    async with async_session() as session:
        hall = await session.get(Hall, hall_id, options=[selectinload(Hall.tables)])
        if not hall:
            raise HTTPException(status_code=404, detail="Hall not found")

        data = patch.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(hall, k, v)

        await session.commit()
        await session.refresh(hall)
        return HallOut.model_validate(hall)


# -------------------------
# Tables
# -------------------------


@hall_router.get("/halls/{hall_id}/tables", response_model=List[TableOut])
async def list_tables(hall_id: str):
    async with async_session() as session:
        res = await session.execute(select(Table).where(Table.hall_id == hall_id))
        tables = list(res.scalars().all())
        tables.sort(key=lambda t: t.number)
        return [TableOut.model_validate(t) for t in tables]


@hall_router.post("/halls/{hall_id}/tables", response_model=TableOut)
async def create_table(hall_id: str, payload: TableCreateRequest):
    async with async_session() as session:
        hall = await session.get(Hall, hall_id)
        if not hall:
            raise HTTPException(status_code=404, detail="Hall not found")

        table = Table(
            id=payload.id or gen_id("TBL"),
            hall_id=hall_id,
            number=payload.number,
            x=payload.x,
            y=payload.y,
            width=payload.width,
            height=payload.height,
            rotation=payload.rotation,
            border_radius=payload.border_radius,
            status=payload.status,
        )

        session.add(table)
        try:
            await session.commit()
        except Exception as e:  # pragma: no cover
            await session.rollback()
            # UniqueConstraint(hall_id, number)
            raise HTTPException(status_code=400, detail=f"Cannot create table: {e}")

        await session.refresh(table)
        return TableOut.model_validate(table)


@hall_router.patch("/tables/{table_id}", response_model=TableOut)
async def patch_table(table_id: str, patch: TablePatchRequest):
    async with async_session() as session:
        table = await session.get(Table, table_id)
        if not table:
            raise HTTPException(status_code=404, detail="Table not found")

        data = patch.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(table, k, v)

        try:
            await session.commit()
        except Exception as e:  # pragma: no cover
            await session.rollback()
            raise HTTPException(status_code=400, detail=f"Cannot patch table: {e}")

        await session.refresh(table)
        return TableOut.model_validate(table)


# -------------------------
# Menu
# -------------------------


@menu_router.get("/workplaces/{workplace_id}/menu", response_model=List[MenuCategoryOut])
async def get_menu(workplace_id: str, active_only: bool = Query(default=False)):
    async with async_session() as session:
        q = select(MenuCategory).options(selectinload(MenuCategory.items)).where(MenuCategory.workplace_id == workplace_id)
        if active_only:
            q = q.where(MenuCategory.is_active.is_(True))
        res = await session.execute(q)
        categories = list(res.scalars().all())
        categories.sort(key=lambda c: c.position)
        for c in categories:
            c.items.sort(key=lambda i: i.position)
            if active_only:
                c.items = [i for i in c.items if i.is_active]
        return [MenuCategoryOut.model_validate(c) for c in categories]


@menu_router.post("/workplaces/{workplace_id}/menu/categories", response_model=MenuCategoryOut)
async def create_menu_category(workplace_id: str, payload: MenuCategoryCreateRequest):
    async with async_session() as session:
        wp = await session.get(Workplace, workplace_id)
        if not wp:
            raise HTTPException(status_code=404, detail="Workplace not found")

        cat = MenuCategory(
            id=payload.id or gen_id("CAT"),
            workplace_id=workplace_id,
            title=payload.title,
            position=payload.position,
            is_active=payload.is_active,
        )
        session.add(cat)
        await session.commit()
        await session.refresh(cat)
        return MenuCategoryOut.model_validate(cat)


@menu_router.patch("/menu/categories/{category_id}", response_model=MenuCategoryOut)
async def patch_menu_category(category_id: str, patch: MenuCategoryPatchRequest):
    async with async_session() as session:
        cat = await session.get(MenuCategory, category_id, options=[selectinload(MenuCategory.items)])
        if not cat:
            raise HTTPException(status_code=404, detail="Menu category not found")

        data = patch.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(cat, k, v)

        await session.commit()
        await session.refresh(cat)
        return MenuCategoryOut.model_validate(cat)


@menu_router.post("/menu/categories/{category_id}/items", response_model=MenuItemOut)
async def create_menu_item(category_id: str, payload: MenuItemCreateRequest):
    async with async_session() as session:
        cat = await session.get(MenuCategory, category_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Menu category not found")

        item = MenuItem(
            id=payload.id or gen_id("MNU"),
            category_id=category_id,
            title=payload.title,
            description=payload.description,
            portion=payload.portion,
            price=payload.price,
            position=payload.position,
            is_active=payload.is_active,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return MenuItemOut.model_validate(item)


@menu_router.patch("/menu/items/{item_id}", response_model=MenuItemOut)
async def patch_menu_item(item_id: str, patch: MenuItemPatchRequest):
    async with async_session() as session:
        item = await session.get(MenuItem, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Menu item not found")

        data = patch.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(item, k, v)

        await session.commit()
        await session.refresh(item)
        return MenuItemOut.model_validate(item)


# -------------------------
# Shifts
# -------------------------


@shifts_router.get("/workplaces/{workplace_id}/shifts", response_model=List[ShiftOut])
async def list_shifts(workplace_id: str, limit: int = Query(default=50, ge=1, le=200)):
    async with async_session() as session:
        res = await session.execute(
            select(Shift)
            .where(Shift.workplace_id == workplace_id)
            .order_by(Shift.start_time.desc())
            .limit(limit)
        )
        shifts = list(res.scalars().all())
        return [ShiftOut.model_validate(s) for s in shifts]


@shifts_router.post("/workplaces/{workplace_id}/shifts", response_model=ShiftOut)
async def create_shift(workplace_id: str, payload: ShiftCreateRequest):
    """Open shift for workplace.

    MVP rule: only one open shift per workplace. If one already exists, return it.
    """
    async with async_session() as session:
        wp = await session.get(Workplace, workplace_id)
        if not wp:
            raise HTTPException(status_code=404, detail="Workplace not found")

        existing_open = await session.scalar(
            select(Shift).where(Shift.workplace_id == workplace_id, Shift.is_closed.is_(False))
        )
        if existing_open:
            return ShiftOut.model_validate(existing_open)

        shift = Shift(
            id=payload.id or gen_id("SFT"),
            workplace_id=workplace_id,
            start_time=payload.start_time or utc_ts(),
            is_closed=False,
            end_time=0,
            place_work_title=wp.title,
            currency=wp.currency,
            service_percent=payload.service_percent if payload.service_percent is not None else wp.service_percent_default,
            shift_type=payload.shift_type if payload.shift_type is not None else wp.shift_type_default,
            pay_for_shift=float(payload.pay_for_shift) if payload.pay_for_shift is not None else float(wp.pay_for_shift_default),
            total_pay_for_shift=float(payload.pay_for_shift) if payload.pay_for_shift is not None else float(wp.pay_for_shift_default),
            total_tips=0,
            total_cash_register=0,
            order_count=0,
            duration=0,
        )

        session.add(shift)
        await session.commit()
        await session.refresh(shift)
        return ShiftOut.model_validate(shift)


@shifts_router.get("/shifts/{shift_id}", response_model=ShiftOut)
async def get_shift(shift_id: str):
    async with async_session() as session:
        shift = await session.get(Shift, shift_id)
        if not shift:
            raise HTTPException(status_code=404, detail="Shift not found")
        return ShiftOut.model_validate(shift)


@shifts_router.patch("/shifts/{shift_id}", response_model=ShiftOut)
async def patch_shift(shift_id: str, patch: ShiftPatchRequest):
    async with async_session() as session:
        shift = await session.get(Shift, shift_id)
        if not shift:
            raise HTTPException(status_code=404, detail="Shift not found")

        data = patch.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(shift, k, v)

        # convenience: if closing shift without end_time
        if shift.is_closed and (not shift.end_time):
            shift.end_time = utc_ts()

        await _recalc_shift_aggregates(session, shift_id)
        await session.commit()
        await session.refresh(shift)
        return ShiftOut.model_validate(shift)


# -------------------------
# Orders
# -------------------------


@orders_router.get("/shifts/{shift_id}/orders", response_model=List[OrderOut])
async def list_orders(shift_id: str):
    async with async_session() as session:
        res = await session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.shift_id == shift_id)
            .order_by(Order.created_at.desc())
        )
        orders = list(res.scalars().all())
        return [OrderOut.model_validate(o) for o in orders]


@orders_router.post("/shifts/{shift_id}/orders", response_model=OrderOut)
async def create_order(shift_id: str, payload: OrderCreateRequest):
    async with async_session() as session:
        shift = await session.get(Shift, shift_id)
        if not shift:
            raise HTTPException(status_code=404, detail="Shift not found")
        if shift.is_closed:
            raise HTTPException(status_code=409, detail="Shift is closed")

        hall_name: Optional[str] = None
        table_number: Optional[int] = None

        if payload.hall_id:
            hall = await session.get(Hall, payload.hall_id)
            if not hall:
                raise HTTPException(status_code=404, detail="Hall not found")
            hall_name = hall.name

        if payload.table_id:
            table = await session.get(Table, payload.table_id)
            if not table:
                raise HTTPException(status_code=404, detail="Table not found")
            table_number = table.number

        order = Order(
            id=payload.id or gen_id("ORD"),
            shift_id=shift_id,
            hall_id=payload.hall_id,
            table_id=payload.table_id,
            table_number=table_number,
            hall_name=hall_name,
            comments=payload.comments,
            created_at=utc_ts(),
            updated_at=utc_ts(),
            closed_at=0,
            tips=float(payload.tips or 0),
            total_price=float(payload.total_price or 0),
            is_paid=False,
            is_done=False,
        )
        session.add(order)
        await session.flush()  # order.id available for items

        # order items
        for it in payload.items:
            oi = OrderItem(
                id=it.id or gen_id("ITM"),
                order_id=order.id,
                menu_item_id=it.menu_item_id,
                title=it.title,
                price=float(it.price),
                quantity=int(it.quantity),
                total_price=float(it.price) * int(it.quantity),
                comment=it.comment,
            )
            session.add(oi)

        # Update table UI cache
        if payload.table_id:
            table = await session.get(Table, payload.table_id)
            if table:
                table.order_id = order.id
                table.status = "occupied"

        await _recalc_shift_aggregates(session, shift_id)
        await session.commit()

        order = await session.get(Order, order.id, options=[selectinload(Order.items)])
        return OrderOut.model_validate(order)


@orders_router.patch("/orders/{order_id}", response_model=OrderOut)
async def patch_order(order_id: str, patch: OrderPatchRequest):
    async with async_session() as session:
        order = await session.get(Order, order_id, options=[selectinload(Order.items)])
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        data = patch.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(order, k, v)

        order.updated_at = utc_ts()

        # If paid: close order and free table UI cache
        if order.is_paid:
            if not order.closed_at:
                order.closed_at = patch.closed_at or utc_ts()
            if order.table_id:
                table = await session.get(Table, order.table_id)
                if table and table.order_id == order.id:
                    table.order_id = None
                    table.status = "free"

        await _recalc_shift_aggregates(session, order.shift_id)
        await session.commit()
        await session.refresh(order)
        return OrderOut.model_validate(order)


@orders_router.post("/orders/{order_id}/items", response_model=OrderItemOut)
async def add_order_item(order_id: str, payload: OrderItemCreateRequest):
    async with async_session() as session:
        order = await session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.is_paid:
            raise HTTPException(status_code=409, detail="Order is already paid")

        item = OrderItem(
            id=payload.id or gen_id("ITM"),
            order_id=order_id,
            menu_item_id=payload.menu_item_id,
            title=payload.title,
            price=float(payload.price),
            quantity=int(payload.quantity),
            total_price=float(payload.price) * int(payload.quantity),
            comment=payload.comment,
        )
        session.add(item)

        order.updated_at = utc_ts()
        await session.commit()
        await session.refresh(item)
        return OrderItemOut.model_validate(item)


@orders_router.patch("/order-items/{item_id}", response_model=OrderItemOut)
async def patch_order_item(item_id: str, patch: OrderItemPatchRequest):
    async with async_session() as session:
        item = await session.get(OrderItem, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Order item not found")

        data = patch.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(item, k, v)

        # keep total_price consistent
        if patch.price is not None or patch.quantity is not None:
            item.total_price = float(item.price) * int(item.quantity)

        order = await session.get(Order, item.order_id)
        if order:
            order.updated_at = utc_ts()

        await session.commit()
        await session.refresh(item)
        return OrderItemOut.model_validate(item)


# -------------------------
# (Optional) Delete endpoints (useful in admin tooling)
# -------------------------


@orders_router.delete("/orders/{order_id}")
async def delete_order(order_id: str):
    async with async_session() as session:
        order = await session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        shift_id = order.shift_id

        # clear table UI cache
        if order.table_id:
            table = await session.get(Table, order.table_id)
            if table and table.order_id == order.id:
                table.order_id = None
                table.status = "free"

        await session.execute(delete(Order).where(Order.id == order_id))
        await _recalc_shift_aggregates(session, shift_id)
        await session.commit()
        return {"ok": True}


# =========================
# Mount routers
# =========================


app.include_router(users_router)
app.include_router(workplaces_router)
app.include_router(hall_router)
app.include_router(menu_router)
app.include_router(shifts_router)
app.include_router(orders_router)

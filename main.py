from __future__ import annotations
import secrets
import string
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import APIRouter, FastAPI, HTTPException, Query, Response, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
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
from reqs import HallCreateRequest, HallPatchUpdate, HallResponse, MenuCategoryCreateRequest, MenuCategoryPatchUpdate, MenuCategoryResponse, MenuItemCreateRequest, MenuItemPatchUpdate, NotesCreateRequest, NotesPatchUpdate, NotesResponse, OrderCreateRequest, OrderPatchUpdate, ShiftCreateRequest, ShiftInHistoryResponse, ShiftPatchUpdate, ShiftResponse, TableCreateRequest, TablePatchUpdate, UserCreateRequest, UserPatchUpdate, UserResponse,WorkplaceCreateRequest, WorkplacePatchUpdate, WorkplaceResponse



from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.sql.schema import Column

# =========================
# Batch delete: schemas
# =========================

EntityName = Literal[
    "users",               # PK: users.id (int)
    "users_by_tg_id",       # key: users.tg_id (bigint) - удобно, раз ты часто работаешь по tg_id
    "workplaces",
    "halls",
    "tables",
    "menu_categories",
    "menu_items",
    "shifts",
    "orders",
    "order_items",
    "notes",
]


class BatchDeleteOp(BaseModel):
    entity: EntityName
    ids: List[Union[str, int]] = Field(..., min_length=1)


class BatchDeleteRequest(BaseModel):
    ops: List[BatchDeleteOp] = Field(..., min_length=1)
    strict: bool = False
    """
    strict=True: если по какой-то операции rowcount == 0 -> кидаем 404.
    strict=False: просто удаляем что можем, rowcount может быть 0 (например, уже удалено каскадом).
    """


class BatchDeleteResponse(BaseModel):
    requested: Dict[str, int]
    deleted: Dict[str, int]
    total_deleted: int


# =========================
# Batch delete: registry
# =========================

# Важно: для "users_by_tg_id" используем не PK, а tg_id колонку.
MODEL_REGISTRY: Dict[str, Tuple[type, Column, type]] = {
    "users": (User, User.__table__.c.id, int),
    "users_by_tg_id": (User, User.__table__.c.tg_id, int),

    "workplaces": (Workplace, Workplace.__table__.c.id, str),
    "halls": (Hall, Hall.__table__.c.id, str),
    "tables": (Table, Table.__table__.c.id, str),

    "menu_categories": (MenuCategory, MenuCategory.__table__.c.id, str),
    "menu_items": (MenuItem, MenuItem.__table__.c.id, str),

    "shifts": (Shift, Shift.__table__.c.id, str),
    "orders": (Order, Order.__table__.c.id, str),
    "order_items": (OrderItem, OrderItem.__table__.c.id, str),

    "notes": (Notes, Notes.__table__.c.id, str),
}


def _cast_ids(ids: List[Union[str, int]], caster: type) -> List[Union[str, int]]:
    out: List[Union[str, int]] = []
    for v in ids:
        if caster is int:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"Invalid int id: {v}")
        else:
            # str
            if v is None:
                raise HTTPException(status_code=422, detail="Invalid str id: null")
            out.append(str(v))
    # убираем дубли, сохраняя порядок
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


async def batch_delete(session, req: BatchDeleteRequest) -> BatchDeleteResponse:
    requested: Dict[str, int] = {}
    deleted_counts: Dict[str, int] = {}
    total_deleted = 0

    # одна транзакция на всё
    async with session.begin():
        for op in req.ops:
            if op.entity not in MODEL_REGISTRY:
                raise HTTPException(status_code=400, detail=f"Unknown entity: {op.entity}")

            model, key_col, caster = MODEL_REGISTRY[op.entity]
            ids = _cast_ids(op.ids, caster)

            requested[op.entity] = len(ids)

            stmt = delete(model).where(key_col.in_(ids))
            result = await session.execute(stmt)

            # result.rowcount в asyncpg обычно доступен
            rowcount = int(result.rowcount or 0)

            if req.strict and rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Nothing deleted for entity={op.entity} ids={ids}",
                )

            deleted_counts[op.entity] = rowcount
            total_deleted += rowcount

    return BatchDeleteResponse(
        requested=requested,
        deleted=deleted_counts,
        total_deleted=total_deleted,
    )

# =========================
# FastAPI app
# =========================


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="Waiter Note API", lifespan=lifespan)
@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    # важно для оффлайн-синка: повторный create -> 409, а не 500
    return JSONResponse(status_code=409, content={"detail": "Already exists"})

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

admin_router = APIRouter(prefix="/api", tags=["batch"])
users_router = APIRouter(prefix="/api/users", tags=["users"])
workplaces_router = APIRouter(prefix="/api/workplaces", tags=["workplaces"])
hall_router = APIRouter(prefix="/api", tags=["halls"])
menu_router = APIRouter(prefix="/api", tags=["menu"])
shifts_router = APIRouter(prefix="/api", tags=["shifts"])


# =========================
# Helpers
# =========================

async def gen_id(prefix: str) -> str:
    """Generate an ID that fits models.ID21 (String(21)).

    Project uses IDs like:
      - WPL00000000000000001  (len(prefix_with_underscore)=4  -> 17 digits)
      - HALL0000000000000001  (len(prefix_with_underscore)=5  -> 16 digits)

    We therefore compute suffix length dynamically to keep total length == 21.
    """

    if not prefix:
        raise ValueError("prefix must be non-empty")
    p = prefix.upper().rstrip("_")
    if not p.isalnum():
        raise ValueError("prefix must be alphanumeric")

    prefixx = f"{p}"
    digits_len = 21 - len(prefixx)
    if digits_len <= 0:
        raise ValueError("prefix is too long for ID21")

    suffix = "".join(secrets.choice(string.digits) for _ in range(digits_len))
    return f"{prefixx}{suffix}"


@admin_router.post("/batch-delete", response_model=BatchDeleteResponse, status_code=200)
async def api_batch_delete(req: BatchDeleteRequest):
    async with async_session() as session:
        res = await batch_delete(session, req)
        await session.commit()
        return res

# -------------------------
# api reqqs
# -------------------------
@users_router.patch("/{tg_id}", status_code=200)
async def update_user(tg_id: int, data: UserPatchUpdate):
    """Update an existing user."""
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.tg_id == tg_id)
            )
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")

            update_data = data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(user, key, value)
            user.updated_at = utc_ts()
        await session.commit()
        await session.refresh(user)
        return "User updated successfully"
@users_router.get("/{tg_id}", response_model=UserResponse)
async def get_user(tg_id: int):
    async with async_session() as session:
        stmt = (
            select(User)
            .where(User.tg_id == tg_id)
            .options(selectinload(User.workplaces))
        )
        user = await session.scalar(stmt)

        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        # сортировка по position (если важно)
        user.workplaces.sort(key=lambda w: w.position)

        return UserResponse.model_validate(user)


@users_router.post("/", status_code=201)
async def create_user(req: UserCreateRequest):
    """Create a new user."""
    async with async_session() as session:
        async with session.begin():
            user = User(
                id=req.id,
                tg_id=req.tg_id,
                username=req.username,
                language=req.language,
                timezone=req.timezone,
                is_onboarding_completed=False,
                is_disabled=False,
                created_at=utc_ts(),
                updated_at=utc_ts(),
            )
            session.add(user)
        await session.commit()
        await session.refresh(user)
        return "User created successfully"
    
@workplaces_router.patch("/{workplace_id}", status_code=200)
async def update_workplace(workplace_id: str, req: WorkplacePatchUpdate):
    """Update an existing workplace."""
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(Workplace).where(Workplace.id == workplace_id)
            )
            workplace = result.scalar_one_or_none()
            if workplace is None:
                raise HTTPException(status_code=404, detail="Workplace not found")

            update_data = req.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(workplace, key, value)
            workplace.updated_at = utc_ts()
        await session.commit()
        await session.refresh(workplace)
        return "Workplace updated successfully"
@workplaces_router.get("/{workplace_id}", response_model=WorkplaceResponse)
async def get_workplace(workplace_id: str):
    async with async_session() as session:
        result = await session.execute(
            select(Workplace).where(Workplace.id == workplace_id)
        )
        workplace = result.scalar_one_or_none()
        if workplace is None:
            raise HTTPException(status_code=404, detail="Workplace not found")
        return WorkplaceResponse.model_validate(workplace)
@workplaces_router.post("/", status_code=201)
async def create_workplace(req: WorkplaceCreateRequest):
    """Create a new workplace."""
    async with async_session() as session:
        async with session.begin():
            workplace = Workplace(
                id=req.id,
                user_id=req.user_id,
                
                title=req.title,
                timezone=req.timezone,
                currency=req.currency,

                service_percent_default=req.service_percent_default,
                shift_type_default=req.shift_type_default,
                pay_for_shift_default=req.pay_for_shift_default,

                position=req.position,
                is_archived=req.is_archived,

                created_at=utc_ts(),
                updated_at=utc_ts(),
            )
            session.add(workplace)
        await session.commit()
        await session.refresh(workplace)
        return "Workplace created successfully"



@shifts_router.get("/workplaces/{workplace_id}/shifts", response_model=List[ShiftInHistoryResponse])
async def get_shifts_by_period_for_workplace(
    workplace_id: str,
    start_ts: Optional[int] = Query(None, alias="startTs"),
    end_ts: Optional[int] = Query(None, alias="endTs"),
):
    async with async_session() as session:
        stmt = select(Shift).where(Shift.workplace_id == workplace_id)

        if start_ts is not None:
            stmt = stmt.where(Shift.start_time >= start_ts)
        if end_ts is not None:
            stmt = stmt.where(Shift.start_time <= end_ts)

        stmt = stmt.order_by(Shift.start_time.desc())

        result = await session.execute(stmt)
        shifts = result.scalars().all()

        return [ShiftInHistoryResponse.model_validate(shift) for shift in shifts]

@shifts_router.get("/workplaces/{workplace_id}/shifts/{shift_id}", response_model=ShiftResponse)
async def get_shift_for_workplace_with_orders_and_order_items(workplace_id: str, shift_id: str):
    async with async_session() as session:
        stmt = (
            select(Shift)
            .where(Shift.workplace_id == workplace_id, Shift.id == shift_id)
            .options(selectinload(Shift.orders).selectinload(Order.items))
        )
        result = await session.execute(stmt)
        shift = result.scalar_one_or_none()
        if shift is None:
            raise HTTPException(status_code=404, detail="Shift not found")
        return ShiftResponse.model_validate(shift)

@shifts_router.patch(
    "/workplaces/{workplace_id}/shifts/active/orders/{order_id}",
    status_code=200,
)
async def update_order_with_items_for_active_shift(
    workplace_id: str,
    order_id: str,
    req: OrderPatchUpdate,
):
    async with async_session() as session:
        async with session.begin():
            shift = await session.scalar(
                select(Shift).where(Shift.workplace_id == workplace_id, Shift.is_closed == False)
            )
            if shift is None:
                raise HTTPException(status_code=404, detail="Active shift not found")

            order = await session.scalar(
                select(Order).where(Order.id == order_id, Order.shift_id == shift.id)
            )
            if order is None:
                raise HTTPException(status_code=404, detail="Order not found")

            update_data = req.model_dump(exclude_unset=True, exclude={"items"})
            for key, value in update_data.items():
                setattr(order, key, value)
            order.updated_at = utc_ts()

            await session.execute(delete(OrderItem).where(OrderItem.order_id == order.id))

            if req.items is not None:
                await session.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
                for item_req in (req.items or []):
                    session.add(
                        OrderItem(
                            id=item_req.id,
                            order_id=order.id,
                            menu_item_id=item_req.menu_item_id,
                            title=item_req.title,
                            quantity=item_req.quantity,
                            price=item_req.price,
                            total_price=item_req.total_price,
                            comment=item_req.comment,
                        )
                    )

        await session.commit()
        return "Order with items updated successfully"


@shifts_router.post(
    "/workplaces/{workplace_id}/shifts/active/orders",
    status_code=201,
)
async def create_order_with_items_for_active_shift(workplace_id: str, req: OrderCreateRequest):
    async with async_session() as session:
        async with session.begin():
            shift = await session.scalar(
                select(Shift).where(Shift.workplace_id == workplace_id, Shift.is_closed == False)
            )
            if shift is None:
                raise HTTPException(status_code=404, detail="Active shift not found")
            order_id = req.id or await gen_id("ORD")
            created_at = req.created_at or utc_ts()
            order = Order(
                id=order_id,
                shift_id=shift.id,
                hall_id=req.hall_id,
                table_id=req.table_id,
                table_number=req.table_number,
                hall_name=req.hall_name,
                comments=req.comments,
                closed_at=0,

                is_paid=req.is_paid,
                is_done=req.is_done,
                tips=req.tips,
                total_price=req.total_price,

                created_at=created_at,
                updated_at=created_at,
             )
            session.add(order)


            for item_req in (req.items or []):
                 session.add(
                     OrderItem(

                        id=item_req.id or await gen_id("ORDITM"),
                        order_id=order_id,
                        menu_item_id=item_req.menu_item_id,
                        title=item_req.title,
                        quantity=item_req.quantity,
                        price=item_req.price,
                        total_price=item_req.total_price,
                        comment=item_req.comment,
                     )
                 )

        await session.commit()
        return "Order with items created successfully"
    
        
@shifts_router.get("/workplaces/{workplace_id}/shifts/active", response_model=ShiftResponse)
async def get_active_shift_for_workplace_with_orders_and_order_items(workplace_id: str):
    async with async_session() as session:
        stmt = (
            select(Shift)
            .where(Shift.workplace_id == workplace_id, Shift.is_closed == False)
            .options(selectinload(Shift.orders).selectinload(Order.items))
        )
        result = await session.execute(stmt)
        shift = result.scalar_one_or_none()
        if shift is None:
            raise HTTPException(status_code=404, detail="Active shift not found")
        return ShiftResponse.model_validate(shift)

    
@shifts_router.patch("/workplaces/{workplace_id}/shifts/{shift_id}", status_code=200)
async def update_shift(workplace_id: str, shift_id: str, req: ShiftPatchUpdate):
    """Update an existing shift."""
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(Shift).where(
                    Shift.id == shift_id,
                    Shift.workplace_id == workplace_id,
                )
            )
            shift = result.scalar_one_or_none()
            if shift is None:
                raise HTTPException(status_code=404, detail="Shift not found")

            update_data = req.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(shift, key, value)
        await session.commit()
        await session.refresh(shift)
        return "Shift updated successfully"
@shifts_router.post("/workplaces/{workplace_id}/shifts", status_code=201)
async def create_shift_for_workplace(workplace_id: str, req: ShiftCreateRequest):
    """Create a new shift for a workplace."""
    async with async_session() as session:
        async with session.begin():
            shift = Shift(
                id=req.id,
                workplace_id=workplace_id,
                start_time=req.start_time,
                is_closed=False,
                end_time=0,
                place_work_title=req.place_work_title,
                currency=req.currency,
                pay_for_shift=req.pay_for_shift,
                service_percent=req.service_percent,
                shift_type=req.shift_type,
                total_pay_for_shift=0,
                total_tips=0,
                total_cash_register=0,
                order_count=0,
                duration=0,
            )
            session.add(shift)
        await session.commit()
        await session.refresh(shift)
        return "Shift created successfully"




@users_router.patch("/{user_id}/notes/{note_id}", status_code=200)
async def update_user_note(user_id: int, note_id: str, req: NotesPatchUpdate):
    """Update an existing note for a user."""
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(Notes).where(
                    Notes.id == note_id,
                    Notes.user_id == user_id,
                )
            )
            note = result.scalar_one_or_none()
            if note is None:
                raise HTTPException(status_code=404, detail="Note not found")

            update_data = req.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(note, key, value)
            note.updated_at = utc_ts()
        await session.commit()
        await session.refresh(note)
        return "Note updated successfully"

@users_router.post("/{user_id}/notes", status_code=201)
async def create_user_note(user_id: int, req: NotesCreateRequest):
    """Create a new note for a user."""
    async with async_session() as session:
        async with session.begin():
            note = Notes(
                id=req.id,
                user_id=user_id,
                scope=req.scope,
                workplace_id=req.workplace_id,
                shift_id=req.shift_id,
                header=req.header,
                content=req.content,
                pinned=req.pinned,
                archived=req.archived,
                created_at=utc_ts(),
                updated_at=utc_ts(),
            )
            session.add(note)
        await session.commit()
        await session.refresh(note)
        return "Note created successfully"
@users_router.get("/{user_id}/notes", response_model=List[NotesResponse])
async def get_user_notes(user_id: int):
    async with async_session() as session:
        stmt = select(Notes).where(Notes.user_id == user_id)
        result = await session.execute(stmt)
        notes = result.scalars().all()
        return [NotesResponse.model_validate(note) for note in notes]



@hall_router.patch("/workplaces/{workplace_id}/halls/{hall_id}", status_code=200)
async def update_hall(workplace_id: str, hall_id: str, req: HallPatchUpdate):
    """Update an existing hall."""
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(Hall).where(
                    Hall.id == hall_id,
                    Hall.workplace_id == workplace_id,
                )
            )
            hall = result.scalar_one_or_none()
            if hall is None:
                raise HTTPException(status_code=404, detail="Hall not found")

            update_data = req.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(hall, key, value)
            
        await session.commit()
        await session.refresh(hall)
        return "Hall updated successfully"
@hall_router.post("/workplaces/{workplace_id}/halls", status_code=201)
async def create_hall_for_workplace(workplace_id: str, req: HallCreateRequest):
    """Create a new hall for a workplace."""
    async with async_session() as session:
        async with session.begin():
            hall = Hall(
                id=req.id,
                workplace_id=workplace_id,
                name=req.name,
                position=req.position,
                width=req.width,
                height=req.height,
                scale=req.scale,
            )
            session.add(hall)
        await session.commit()
        await session.refresh(hall)
        return "Hall created successfully"
@hall_router.get("/workplaces/{workplace_id}/halls", response_model=List[HallResponse])
async def get_halls_for_workplace(workplace_id: str):
    async with async_session() as session:
        stmt = (
            select(Hall)
            .where(Hall.workplace_id == workplace_id)
            .options(selectinload(Hall.tables))
            .order_by(Hall.position)
        )
        result = await session.execute(stmt)
        halls = result.scalars().all()

        # Sort tables within each hall by number
        for hall in halls:
            hall.tables.sort(key=lambda table: table.number)

        return [HallResponse.model_validate(hall) for hall in halls]
@hall_router.post("/workplaces/{workplace_id}/halls/{hall_id}/tables", status_code=201)
async def create_table_for_hall(workplace_id: str, hall_id: str, req: TableCreateRequest):
    """Create a new table under a specific hall for a workplace."""
    async with async_session() as session:
        async with session.begin():
            table = Table(
                id=req.id,
                hall_id=hall_id,
                number=req.number,
                x=req.x,
                y=req.y,
                width=req.width,
                height=req.height,
                rotation=req.rotation,
                border_radius=req.border_radius,
                status="free",
                
            )
            session.add(table)
        await session.commit()
        await session.refresh(table)
        return "Table created successfully"
@hall_router.patch("/workplaces/{workplace_id}/halls/{hall_id}/tables/{table_id}", status_code=200)
async def update_table(workplace_id: str, hall_id: str, table_id: str, req: TablePatchUpdate):
    """Update an existing table."""
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(Table).where(
                    Table.id == table_id,
                    Table.hall_id == hall_id,
                )
            )
            table = result.scalar_one_or_none()
            if table is None:
                raise HTTPException(status_code=404, detail="Table not found")

            update_data = req.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(table, key, value)
            
        await session.commit()
        await session.refresh(table)
        return "Table updated successfully"

@menu_router.patch("/workplaces/{workplace_id}/menu-categories/{category_id}", status_code=200)
async def update_menu_category(workplace_id: str, category_id: str, req: MenuCategoryPatchUpdate):
    """Update an existing menu category."""
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                select(MenuCategory).where(
                    MenuCategory.id == category_id,
                    MenuCategory.workplace_id == workplace_id,
                )
            )
            category = result.scalar_one_or_none()
            if category is None:
                raise HTTPException(status_code=404, detail="Menu category not found")

            update_data = req.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(category, key, value)
            
        await session.commit()
        await session.refresh(category)
        return "Menu category updated successfully"
@menu_router.post("/workplaces/{workplace_id}/menu-categories", status_code=201)
async def create_menu_category(workplace_id: str, req: MenuCategoryCreateRequest):
    """Create a new menu category for a workplace."""
    async with async_session() as session:
        async with session.begin():
            category = MenuCategory(
                id=req.id,
                workplace_id=workplace_id,
                title=req.title,
                position=req.position,
                is_active=req.is_active,
            )
            session.add(category)
        await session.commit()
        await session.refresh(category)
        return "Menu category created successfully"
@menu_router.get("/workplaces/{workplace_id}/menu-categories", response_model=List[MenuCategoryResponse])
async def get_menu_categories_with_items(workplace_id: str):
    async with async_session() as session:
        stmt = (
            select(MenuCategory)
            .where(MenuCategory.workplace_id == workplace_id)
            .options(selectinload(MenuCategory.items))
            .order_by(MenuCategory.position)
        )
        result = await session.execute(stmt)
        categories = result.scalars().all()

        # Sort items within each category by position
        for category in categories:
            category.items.sort(key=lambda item: item.position)

        return [MenuCategoryResponse.model_validate(cat) for cat in categories]

@menu_router.post("/workplaces/{workplace_id}/menu-categories/{category_id}/items", status_code=201)
async def create_item_for_category(workplace_id: str, category_id: str, req: MenuItemCreateRequest):
    """Create a new menu item under a specific category for a workplace."""
    async with async_session() as session:
        async with session.begin():
            category = await session.scalar(
                select(MenuCategory).where(
                    MenuCategory.id == category_id,
                    MenuCategory.workplace_id == workplace_id,
                )
            )
            if category is None:
                raise HTTPException(status_code=404, detail="Menu category not found")

            item = MenuItem(
                id=req.id,
                category_id=category_id,
                title=req.title,
                description=req.description,
                portion=req.portion,
                price=req.price,
                position=req.position,
                is_active=req.is_active,
            )
            session.add(item)
        await session.commit()
        await session.refresh(item)
        return "Menu item created successfully"
    
@menu_router.patch("/workplaces/{workplace_id}/menu-categories/{category_id}/items/{item_id}", status_code=200)
async def update_menu_item(workplace_id: str, category_id: str, item_id: str, req: MenuItemPatchUpdate):
    """Update an existing menu item."""
    async with async_session() as session:
        async with session.begin():
            category = await session.scalar(
                select(MenuCategory).where(
                    MenuCategory.id == category_id,
                    MenuCategory.workplace_id == workplace_id,
                )
            )
            if category is None:
                raise HTTPException(status_code=404, detail="Menu category not found")

            result = await session.execute(
                select(MenuItem).where(
                    MenuItem.id == item_id,
                    
                    MenuItem.category_id == category_id,
                )
            )
            item = result.scalar_one_or_none()
            if item is None:
                raise HTTPException(status_code=404, detail="Menu item not found")

            update_data = req.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(item, key, value)
            
        await session.commit()
        await session.refresh(item)
        return "Menu item updated successfully"
    

# =========================
# Mount routers
# =========================


app.include_router(users_router)
app.include_router(workplaces_router)
app.include_router(hall_router)
app.include_router(menu_router)
app.include_router(shifts_router)
app.include_router(admin_router)

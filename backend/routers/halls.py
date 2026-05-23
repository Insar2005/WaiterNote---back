from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select, func, update as sql_update
from sqlalchemy.orm import selectinload

from models import Hall, Table, Workplace, WorkplaceMember
from deps import SessionDep, CurrentUser, WorkplaceDep
from schemas.hall import (
    HallCreate, HallUpdate, HallOut,
    TableCreate, TableUpdate, TableOut,
)
from schemas.common import ReorderRequest


# ===== Access helpers =====

async def get_hall_for_user(
    hall_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Hall:
    """Verify user has access to the workplace this hall belongs to."""
    stmt = (
        select(Hall)
        .join(Workplace, Workplace.id == Hall.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            Hall.id == hall_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    result = await session.execute(stmt)
    hall = result.scalar_one_or_none()
    if hall is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hall not found or access denied")
    return hall


HallDep = Annotated[Hall, Depends(get_hall_for_user)]


async def get_table_for_user(
    table_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Table:
    stmt = (
        select(Table)
        .join(Hall, Hall.id == Table.hall_id)
        .join(Workplace, Workplace.id == Hall.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            Table.id == table_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    result = await session.execute(stmt)
    table = result.scalar_one_or_none()
    if table is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "table not found or access denied")
    return table


TableDep = Annotated[Table, Depends(get_table_for_user)]


# ===== Routers =====

# Halls live nested under workplace for create+list; standalone for the rest
hall_under_wp = APIRouter(prefix="/workplaces/{workplace_id}/halls", tags=["halls"])
hall_router = APIRouter(prefix="/halls", tags=["halls"])


@hall_under_wp.get("", response_model=list[HallOut])
async def list_halls(
    workplace: WorkplaceDep,
    session: SessionDep,
):
    """
    Load entire floor plan: all halls of this workplace with their tables.
    This is the primary endpoint for the Map tab.
    """
    stmt = (
        select(Hall)
        .where(Hall.workplace_id == workplace.id)
        .options(selectinload(Hall.tables))
        .order_by(Hall.position)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@hall_under_wp.post("", response_model=HallOut, status_code=status.HTTP_201_CREATED)
async def create_hall(
    body: HallCreate,
    workplace: WorkplaceDep,
    session: SessionDep,
):
    existing = await session.get(Hall, body.id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "hall id already exists")

    max_pos = await session.scalar(
        select(func.coalesce(func.max(Hall.position), -1))
        .where(Hall.workplace_id == workplace.id)
    )

    hall = Hall(
        id=body.id,
        workplace_id=workplace.id,
        name=body.name,
        width=body.width,
        height=body.height,
        scale=body.scale,
        position=max_pos + 1,
    )
    session.add(hall)
    await session.commit()
    await session.refresh(hall, attribute_names=["tables"])
    return hall


@hall_router.get("/{hall_id}", response_model=HallOut)
async def get_hall(
    hall: HallDep,
    session: SessionDep,
):
    await session.refresh(hall, attribute_names=["tables"])
    return hall


@hall_router.patch("/{hall_id}", response_model=HallOut)
async def update_hall(
    body: HallUpdate,
    hall: HallDep,
    session: SessionDep,
):
    patch = body.model_dump(exclude_unset=True)
    for k, v in patch.items():
        setattr(hall, k, v)
    await session.commit()
    await session.refresh(hall, attribute_names=["tables"])
    return hall


@hall_router.delete("/{hall_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hall(
    hall: HallDep,
    session: SessionDep,
):
    """Cascades to tables. Orders that referenced these tables get table_id=NULL
    (snapshots in Order.table_number/hall_name preserve history)."""
    await session.delete(hall)
    await session.commit()


@hall_under_wp.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_halls(
    body: ReorderRequest,
    workplace: WorkplaceDep,
    session: SessionDep,
):
    result = await session.execute(
        select(Hall.id).where(
            Hall.workplace_id == workplace.id,
            Hall.id.in_(body.ids),
        )
    )
    valid_ids = {r[0] for r in result.all()}

    for position, hall_id in enumerate(body.ids):
        if hall_id in valid_ids:
            await session.execute(
                sql_update(Hall)
                .where(Hall.id == hall_id)
                .values(position=position)
            )
    await session.commit()


# ===== Tables =====

table_under_hall = APIRouter(prefix="/halls/{hall_id}/tables", tags=["tables"])
table_router = APIRouter(prefix="/tables", tags=["tables"])


@table_under_hall.post("", response_model=TableOut, status_code=status.HTTP_201_CREATED)
async def create_table(
    body: TableCreate,
    hall: HallDep,
    session: SessionDep,
):
    existing = await session.get(Table, body.id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "table id already exists")

    # uq_tables_hall_number prevents duplicates at DB level, but cleaner error here
    dup = await session.scalar(
        select(Table.id).where(
            Table.hall_id == hall.id,
            Table.number == body.number,
        )
    )
    if dup is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"table number {body.number} already exists in this hall",
        )

    table = Table(
        id=body.id,
        hall_id=hall.id,
        number=body.number,
        x=body.x,
        y=body.y,
        width=body.width,
        height=body.height,
        rotation=body.rotation,
        border_radius=body.border_radius,
        status="free",
    )
    session.add(table)
    await session.commit()
    await session.refresh(table)
    return table


@table_router.patch("/{table_id}", response_model=TableOut)
async def update_table(
    body: TableUpdate,
    table: TableDep,
    session: SessionDep,
):
    """
    Catch-all update: position (drag), size (resize), rotation, status, number.

    NOTE: status is editable directly here for manual control by the waiter,
    but normally status changes are driven by orders service:
      - free  -> waiting/occupied : when an order is attached
      - any   -> free             : when the active order is paid
    """
    patch = body.model_dump(exclude_unset=True)

    # If number changes, ensure uniqueness within hall
    if "number" in patch and patch["number"] != table.number:
        dup = await session.scalar(
            select(Table.id).where(
                Table.hall_id == table.hall_id,
                Table.number == patch["number"],
                Table.id != table.id,
            )
        )
        if dup is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"table number {patch['number']} already exists in this hall",
            )

    for k, v in patch.items():
        setattr(table, k, v)

    await session.commit()
    await session.refresh(table)
    return table


@table_router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table(
    table: TableDep,
    session: SessionDep,
):
    """Active orders' table_id becomes NULL via FK SET NULL.
    Snapshots in Order.table_number/hall_name preserve history."""
    await session.delete(table)
    await session.commit()
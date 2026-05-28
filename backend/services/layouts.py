"""
Hall layout (table arrangement template) business logic.

Conventions match other services here:
  - Session is provided by the router. Services don't commit.
  - Errors raise HTTPException with appropriate status codes.
  - Access checks happen at the router layer (workplace membership).
"""
from typing import Dict
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Hall, HallLayout, Order, Table, TablePosition


async def list_layouts(session: AsyncSession, hall_id: str) -> list[HallLayout]:
    """Return all layouts of a hall, oldest first, with positions eagerly loaded."""
    from sqlalchemy.orm import selectinload

    stmt = (
        select(HallLayout)
        .where(HallLayout.hall_id == hall_id)
        .options(selectinload(HallLayout.positions))
        .order_by(HallLayout.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_layout(session: AsyncSession, layout_id: str) -> HallLayout:
    """Fetch one layout with positions. 404 if missing."""
    from sqlalchemy.orm import selectinload

    stmt = (
        select(HallLayout)
        .where(HallLayout.id == layout_id)
        .options(selectinload(HallLayout.positions))
    )
    result = await session.execute(stmt)
    layout = result.scalar_one_or_none()
    if not layout:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон не найден")
    return layout


async def create_layout_from_current(
    session: AsyncSession,
    *,
    layout_id: str,
    hall: Hall,
    name: str,
) -> HallLayout:
    """
    Snapshot the hall's current table arrangement into a new layout. The
    layout's positions are derived from live `Table` rows — the caller
    doesn't supply them, which keeps the contract simple ("save what's on
    screen now").
    """
    # Fetch current tables for the hall
    tables_stmt = select(Table).where(Table.hall_id == hall.id)
    tables = (await session.execute(tables_stmt)).scalars().all()

    from utils.ids import new_id

    layout = HallLayout(id=layout_id, hall_id=hall.id, name=name)
    session.add(layout)

    for t in tables:
        session.add(
            TablePosition(
                id=new_id(),
                layout_id=layout_id,
                table_number=t.number,
                x=t.x,
                y=t.y,
                width=t.width,
                height=t.height,
                rotation=t.rotation,
                border_radius=t.border_radius,
            )
        )

    await session.flush()
    # Re-fetch with positions eagerly loaded so the response includes them.
    return await get_layout(session, layout_id)


async def rename_layout(
    session: AsyncSession,
    layout: HallLayout,
    name: str,
) -> HallLayout:
    layout.name = name
    await session.flush()
    return layout


async def delete_layout(session: AsyncSession, layout: HallLayout) -> None:
    """Cascade deletes positions via the relationship."""
    await session.delete(layout)
    await session.flush()


async def apply_layout(
    session: AsyncSession,
    *,
    layout: HallLayout,
    delete_extras: bool,
    new_table_ids: Dict[int, str],
) -> dict:
    """
    Apply a layout to its hall.

    Logic mirrors the frontend mocks (mocks/handlers.js → applyLayout):
      - For each TablePosition: find existing Table by number → move,
        or create new Table using new_table_ids[number] as the id.
      - If delete_extras: drop tables in the hall whose number isn't in
        the layout, EXCEPT those with an active order (those are kept
        and reported back).

    Returns: { moved: [ids], created: [ids], kept_extras: [...], deleted_extras: [ids] }
    """
    hall_id = layout.hall_id

    # Fetch current tables for the hall
    tables_stmt = select(Table).where(Table.hall_id == hall_id)
    tables = list((await session.execute(tables_stmt)).scalars().all())
    by_number = {t.number: t for t in tables}

    layout_numbers = {p.table_number for p in layout.positions}

    moved: list[str] = []
    created: list[str] = []
    kept_extras: list[dict] = []
    deleted_extras: list[str] = []

    # Pass 1: move existing, create missing
    for pos in layout.positions:
        existing = by_number.get(pos.table_number)
        if existing:
            existing.x = pos.x
            existing.y = pos.y
            existing.width = pos.width
            existing.height = pos.height
            existing.rotation = pos.rotation
            existing.border_radius = pos.border_radius
            moved.append(existing.id)
        else:
            # Use client-provided id (the frontend pre-generates stable
            # nanoids so it can pulse the new table immediately).
            tid = new_table_ids.get(pos.table_number)
            if not tid:
                # Fallback — generate server-side. Shouldn't happen with
                # the current frontend, but the API contract allows it.
                from utils.ids import new_id
                tid = new_id()

            session.add(
                Table(
                    id=tid,
                    hall_id=hall_id,
                    order_id=None,
                    number=pos.table_number,
                    x=pos.x,
                    y=pos.y,
                    width=pos.width,
                    height=pos.height,
                    rotation=pos.rotation,
                    border_radius=pos.border_radius,
                    status="free",
                )
            )
            created.append(tid)

    # Pass 2: handle extras (tables in hall but not in layout)
    if delete_extras:
        extras = [t for t in tables if t.number not in layout_numbers]
        for t in extras:
            # Safety: never delete a table that has an active order attached
            # to it. We check both directions for robustness:
            #   - Table.order_id pointing to something
            #   - Any unpaid Order whose table_id matches
            has_attached = t.order_id is not None
            unpaid_stmt = select(Order).where(
                Order.table_id == t.id,
                Order.is_paid.is_(False),
            ).limit(1)
            has_unpaid = (await session.execute(unpaid_stmt)).scalar_one_or_none() is not None

            if has_attached or has_unpaid:
                kept_extras.append(
                    {"id": t.id, "number": t.number, "reason": "active_order"}
                )
                continue

            # Detach any historical (paid) order references, then delete.
            from sqlalchemy import update
            await session.execute(
                update(Order).where(Order.table_id == t.id).values(table_id=None)
            )
            await session.delete(t)
            deleted_extras.append(t.id)

    await session.flush()

    return {
        "moved": moved,
        "created": created,
        "kept_extras": kept_extras,
        "deleted_extras": deleted_extras,
    }
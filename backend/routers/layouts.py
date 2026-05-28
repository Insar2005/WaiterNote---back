"""
Hall layouts router.

Endpoints:
  GET    /halls/{hall_id}/layouts            list saved templates
  POST   /halls/{hall_id}/layouts            save current arrangement as template
  PATCH  /layouts/{layout_id}                rename
  DELETE /layouts/{layout_id}                delete
  POST   /layouts/{layout_id}/apply          apply template to its hall
"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from models import Hall, HallLayout, Workplace, WorkplaceMember
from deps import SessionDep, CurrentUser
from routers.halls import HallDep
from schemas.layout import (
    HallLayoutCreate,
    HallLayoutUpdate,
    HallLayoutOut,
    LayoutApplyBody,
    LayoutApplyResult,
)
from services import layouts as layout_service


# ===== Access helper =====

async def get_layout_for_user(
    layout_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> HallLayout:
    """
    Resolve a layout and verify the requesting user can access its hall's
    workplace. Joins through Hall → Workplace → WorkplaceMember; same
    pattern as the halls router uses.
    """
    stmt = (
        select(HallLayout)
        .join(Hall, Hall.id == HallLayout.hall_id)
        .join(Workplace, Workplace.id == Hall.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            HallLayout.id == layout_id,
            WorkplaceMember.user_id == user.id,
        )
        .options(selectinload(HallLayout.positions))
    )
    result = await session.execute(stmt)
    layout = result.scalar_one_or_none()
    if layout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "layout not found or access denied")
    return layout


LayoutDep = Annotated[HallLayout, Depends(get_layout_for_user)]


# ===== Routers =====

# Hall-scoped: list & create
layout_under_hall = APIRouter(prefix="/halls/{hall_id}/layouts", tags=["layouts"])

# Layout-scoped: get / update / delete / apply
layout_router = APIRouter(prefix="/layouts", tags=["layouts"])


@layout_under_hall.get("", response_model=list[HallLayoutOut])
async def list_hall_layouts(hall: HallDep, session: SessionDep):
    return await layout_service.list_layouts(session, hall.id)


@layout_under_hall.post(
    "",
    response_model=HallLayoutOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_hall_layout(
    body: HallLayoutCreate,
    hall: HallDep,
    session: SessionDep,
):
    layout = await layout_service.create_layout_from_current(
        session,
        layout_id=body.id,
        hall=hall,
        name=body.name,
    )
    await session.commit()
    # Re-fetch to populate positions in the response model.
    return await layout_service.get_layout(session, body.id)


@layout_router.patch("/{layout_id}", response_model=HallLayoutOut)
async def update_layout(
    body: HallLayoutUpdate,
    layout: LayoutDep,
    session: SessionDep,
):
    if body.name is not None:
        await layout_service.rename_layout(session, layout, body.name)
    await session.commit()
    return await layout_service.get_layout(session, layout.id)


@layout_router.delete("/{layout_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layout(layout: LayoutDep, session: SessionDep):
    await layout_service.delete_layout(session, layout)
    await session.commit()


@layout_router.post("/{layout_id}/apply", response_model=LayoutApplyResult)
async def apply_layout(
    body: LayoutApplyBody,
    layout: LayoutDep,
    session: SessionDep,
):
    result = await layout_service.apply_layout(
        session,
        layout=layout,
        delete_extras=body.delete_extras,
        new_table_ids=body.new_table_ids,
    )
    await session.commit()
    return result
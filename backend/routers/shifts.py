from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select

from models import Shift, Workplace, WorkplaceMember
from deps import SessionDep, CurrentUser, WorkplaceDep
from schemas.shift import ShiftOpen, ShiftOut
from services.shifts import (
    open_shift as svc_open_shift,
    close_shift as svc_close_shift,
    get_open_shift as svc_get_open_shift,
    recompute_aggregates as svc_recompute,
)


# ===== Access helper =====

async def get_shift_for_user(
    shift_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Shift:
    """User must have access to the shift's workplace."""
    stmt = (
        select(Shift)
        .join(Workplace, Workplace.id == Shift.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            Shift.id == shift_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    result = await session.execute(stmt)
    shift = result.scalar_one_or_none()
    if shift is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "shift not found or access denied")
    return shift


ShiftDep = Annotated[Shift, Depends(get_shift_for_user)]


async def get_own_shift(
    shift: ShiftDep,
    user: CurrentUser,
) -> Shift:
    """Some operations (close, recompute) only the opener can perform."""
    if shift.opened_by_user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "only the shift opener can perform this action",
        )
    return shift


OwnShiftDep = Annotated[Shift, Depends(get_own_shift)]


# ===== Routers =====

shift_under_wp = APIRouter(prefix="/workplaces/{workplace_id}/shifts", tags=["shifts"])
shift_router = APIRouter(prefix="/shifts", tags=["shifts"])


@shift_under_wp.get("/current", response_model=Optional[ShiftOut])
async def get_current_shift(
    workplace: WorkplaceDep,
    user: CurrentUser,
    session: SessionDep,
):
    """
    Returns user's currently-open shift in this workplace, or null.
    Frontend calls this on app start / workplace switch.
    """
    shift = await svc_get_open_shift(session, workplace.id, user.id)
    return shift


@shift_under_wp.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def open_shift(
    body: ShiftOpen,
    workplace: WorkplaceDep,
    user: CurrentUser,
    session: SessionDep,
):
    """Open a new shift, snapshotting current workplace settings."""
    shift = await svc_open_shift(
        session,
        shift_id=body.id,
        workplace=workplace,
        user=user,
    )
    await session.commit()
    await session.refresh(shift)
    return shift


@shift_under_wp.get("", response_model=list[ShiftOut])
async def list_shifts(
    workplace: WorkplaceDep,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    only_mine: bool = Query(True, description="If true, only shifts opened by current user"),
    closed_only: bool = Query(True, description="If true, exclude open shifts"),
):
    """History of shifts in this workplace."""
    stmt = (
        select(Shift)
        .where(Shift.workplace_id == workplace.id)
        .order_by(Shift.start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    if only_mine:
        stmt = stmt.where(Shift.opened_by_user_id == user.id)
    if closed_only:
        stmt = stmt.where(Shift.is_closed.is_(True))

    result = await session.execute(stmt)
    return list(result.scalars().all())


@shift_router.get("/{shift_id}", response_model=ShiftOut)
async def get_shift(shift: ShiftDep):
    return shift


@shift_router.post("/{shift_id}/close", response_model=ShiftOut)
async def close_shift(
    shift: OwnShiftDep,
    session: SessionDep,
    force: bool = Query(False, description="Close even if unpaid orders exist"),
):
    closed = await svc_close_shift(session, shift, force=force)
    await session.commit()
    await session.refresh(closed)
    return closed


@shift_router.post("/{shift_id}/recompute", response_model=ShiftOut)
async def recompute_shift(
    shift: OwnShiftDep,
    session: SessionDep,
):
    """Manual aggregate recomputation. Useful if something looks off."""
    await svc_recompute(session, shift)
    await session.commit()
    await session.refresh(shift)
    return shift


@shift_router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(
    shift: OwnShiftDep,
    session: SessionDep,
):
    """
    Hard delete: cascades to orders and order_items.
    Only allowed if shift is closed (delete-while-open is suspicious — close instead).
    """
    if not shift.is_closed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "cannot delete an open shift; close it first",
        )
    await session.delete(shift)
    await session.commit()
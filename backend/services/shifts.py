"""
Shift business logic: open, close, recompute aggregates.

These functions accept a session and DO NOT commit — the caller (router)
is responsible for committing the transaction. This lets us compose them
with other operations atomically.
"""
from fastapi import HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Shift, Order, Workplace, User
from utils.time import utc_ts


async def get_open_shift(
    session: AsyncSession,
    workplace_id: str,
    user_id: int,
) -> Shift | None:
    """Return the currently open shift for (workplace, user), or None."""
    stmt = select(Shift).where(
        Shift.workplace_id == workplace_id,
        Shift.opened_by_user_id == user_id,
        Shift.end_time.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def open_shift(
    session: AsyncSession,
    *,
    shift_id: str,
    workplace: Workplace,
    user: User,
) -> Shift:
    """
    Create a new shift, snapshotting current workplace settings.

    Raises 409 if user already has an open shift in this workplace.
    The DB-level partial unique index (uq_shifts_open_per_user) is the
    real source of truth — this check is just for nicer errors.
    """
    existing = await get_open_shift(session, workplace.id, user.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="you already have an open shift in this workplace",
        )

    duplicate_id = await session.get(Shift, shift_id)
    if duplicate_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="shift with this id already exists",
        )

    shift = Shift(
        id=shift_id,
        workplace_id=workplace.id,
        opened_by_user_id=user.id,
        start_time=utc_ts(),
        is_closed=False,
        end_time=None,
        # snapshots
        place_work_title=workplace.title,
        currency=workplace.currency,
        service_percent=workplace.service_percent_default,
        shift_type=workplace.shift_type_default,
        pay_for_shift=workplace.pay_for_shift_default,
        # zero aggregates
        total_pay_for_shift=workplace.pay_for_shift_default,
        total_tips=0.0,
        total_cash_register=0.0,
        order_count=0,
        duration=0,
    )
    session.add(shift)

    # Update user.last_workplace_id — we just chose to work here
    user.last_workplace_id = workplace.id

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="open shift already exists (race)",
        )

    return shift


async def recompute_aggregates(
    session: AsyncSession,
    shift: Shift,
) -> None:
    """
    Recalculate shift aggregates from orders. Mutates shift in-place.
    Source of truth: paid orders only.
    """
    stmt = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_price), 0.0),
        func.coalesce(func.sum(Order.tips), 0.0),
    ).where(
        Order.shift_id == shift.id,
        Order.is_paid.is_(True),
    )
    result = await session.execute(stmt)
    paid_count, paid_revenue, paid_tips = result.one()

    shift.order_count = int(paid_count or 0)
    shift.total_cash_register = float(paid_revenue or 0.0)
    shift.total_tips = float(paid_tips or 0.0)

    # total_pay_for_shift = base pay + service%-of-revenue (for percent shifts)
    if shift.shift_type == "percent":
        shift.total_pay_for_shift = round(
            shift.total_cash_register * (shift.service_percent / 100.0),
            2,
        )
    else:  # fixed
        # For fixed shifts the wage is pay_for_shift; tips are separate.
        shift.total_pay_for_shift = float(shift.pay_for_shift)


async def close_shift(
    session: AsyncSession,
    shift: Shift,
    *,
    force: bool = False,
) -> Shift:
    """
    Close a shift. Recomputes aggregates and sets end_time + duration.

    If `force=False` and there are unpaid orders, raises 409 with their count
    so the frontend can prompt the user "you have N unpaid orders, close anyway?".

    If `force=True`, auto-pays every remaining unpaid order with tips=0:
      - is_paid=True, is_done=True, closed_at=now
      - empty orders (no items) are deleted instead of paid — paying an
        empty order would put a zero row into the shift's revenue
      - table is detached (status returns to "free") via the same helper
        the normal pay_order flow uses, so the map stays consistent
      - aggregates are recomputed once at the end, after all auto-pays land

    This matches what the mock backend has been doing all along, which is
    what waiters are used to: closing the shift "tidies up" loose orders
    rather than leaving them dangling for the next session.
    """
    if shift.is_closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="shift is already closed",
        )

    # Pull the actual unpaid orders (with items, so we can decide whether
    # to auto-pay or delete each one). Doing the full SELECT here keeps
    # the rest of the function readable; for normal shifts this list is
    # short, so we don't lose anything by not streaming.
    unpaid_stmt = (
        select(Order)
        .where(
            Order.shift_id == shift.id,
            Order.is_paid.is_(False),
        )
        .options(selectinload(Order.items))
    )
    unpaid_orders = list((await session.execute(unpaid_stmt)).scalars().all())

    if unpaid_orders and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"shift has {len(unpaid_orders)} unpaid orders; "
                "pass force=true to close anyway"
            ),
        )

    now = utc_ts()

    if force and unpaid_orders:
        # Lazy import to avoid a circular import: services.orders imports
        # recompute_aggregates from services.shifts.
        from services.orders import _detach_order_from_table

        for order in unpaid_orders:
            if not order.items:
                # An empty order is a UI artefact — usually a draft that
                # got submitted by accident. Don't pay zero rows into the
                # shift's revenue; just delete + detach the table.
                await _detach_order_from_table(session, order)
                await session.delete(order)
                continue

            order.is_paid = True
            order.is_done = True
            order.tips = 0.0
            order.closed_at = now
            await _detach_order_from_table(session, order)

        # Flush deletes/updates before recompute so the SUM sees the new
        # state. recompute_aggregates uses the DB, not the session cache.
        await session.flush()

    await recompute_aggregates(session, shift)

    shift.end_time = now
    shift.is_closed = True
    shift.duration = max(0, now - shift.start_time)

    return shift
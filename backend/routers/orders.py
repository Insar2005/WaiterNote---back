from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from models import Order, OrderItem, Shift, Workplace, WorkplaceMember
from deps import SessionDep, CurrentUser
from schemas.order import (
    OrderCreate, OrderUpdate, OrderOut,
    OrderItemDraft, OrderItemUpdate, OrderItemsAdd,
    OrderPay, OrderMove, OrderEdit,
)
from services.orders import (
    create_order as svc_create_order,
    add_items as svc_add_items,
    update_item as svc_update_item,
    remove_item as svc_remove_item,
    update_order_meta as svc_update_meta,
    move_order_to_table as svc_move_order,
    pay_order as svc_pay_order,
    delete_order as svc_delete_order,
    reopen_order as svc_reopen_order,
    edit_paid_order as svc_edit_paid_order,
)
from services.shifts import get_open_shift as svc_get_open_shift
from routers.shifts import get_shift_for_user


# ===== Access helpers =====

async def get_order_for_user(
    order_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Order:
    stmt = (
        select(Order)
        .join(Shift, Shift.id == Order.shift_id)
        .join(Workplace, Workplace.id == Shift.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            Order.id == order_id,
            WorkplaceMember.user_id == user.id,
        )
        .options(selectinload(Order.items))
    )
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found or access denied")
    return order


OrderDep = Annotated[Order, Depends(get_order_for_user)]


async def get_order_item_for_user(
    item_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> tuple[OrderItem, Order]:
    """Return both the item and its parent order (already loaded with items)."""
    stmt = (
        select(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Shift, Shift.id == Order.shift_id)
        .join(Workplace, Workplace.id == Shift.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            OrderItem.id == item_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order item not found")

    order_stmt = (
        select(Order)
        .where(Order.id == item.order_id)
        .options(selectinload(Order.items))
    )
    order = (await session.execute(order_stmt)).scalar_one()
    return item, order


# ===== Routers =====

# Listing/creation under shift; single-entity ops standalone
order_under_shift = APIRouter(prefix="/shifts/{shift_id}/orders", tags=["orders"])
order_router = APIRouter(prefix="/orders", tags=["orders"])


@order_under_shift.get("", response_model=list[OrderOut])
async def list_orders(
    shift_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
    only_active: bool = Query(False, description="If true, only unpaid orders"),
    only_paid: bool = Query(False, description="If true, only paid orders"),
):
    # access check via shift
    shift = await get_shift_for_user(shift_id=shift_id, user=user, session=session)

    stmt = (
        select(Order)
        .where(Order.shift_id == shift.id)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    if only_active:
        stmt = stmt.where(Order.is_paid.is_(False))
    if only_paid:
        stmt = stmt.where(Order.is_paid.is_(True))

    result = await session.execute(stmt)
    return list(result.scalars().all())


@order_under_shift.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreate,
    shift_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
):
    shift = await get_shift_for_user(shift_id=shift_id, user=user, session=session)

    # Only the opener can create orders in their shift
    if shift.opened_by_user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "only the shift opener can create orders in this shift",
        )

    order = await svc_create_order(
        session,
        order_id=body.id,
        shift=shift,
        table_id=body.table_id,
        items=[i.model_dump() for i in body.items],
        comments=body.comments,
        guests_count=body.guests_count,
    )
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


# Convenience: create order in user's currently-open shift
order_quick_router = APIRouter(prefix="/workplaces/{workplace_id}/orders", tags=["orders"])


@order_quick_router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order_in_current_shift(
    body: OrderCreate,
    workplace_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
):
    """Shortcut for the Map tab: don't need to know shift_id, just use the open one."""
    # Verify workplace access
    has_access = await session.scalar(
        select(WorkplaceMember.id).where(
            WorkplaceMember.workplace_id == workplace_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    if not has_access:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workplace not found or access denied")

    shift = await svc_get_open_shift(session, workplace_id, user.id)
    if shift is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no open shift in this workplace; open a shift first",
        )

    order = await svc_create_order(
        session,
        order_id=body.id,
        shift=shift,
        table_id=body.table_id,
        items=[i.model_dump() for i in body.items],
        comments=body.comments,
        guests_count=body.guests_count,
    )
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


@order_router.get("/{order_id}", response_model=OrderOut)
async def get_order(order: OrderDep):
    return order


@order_router.patch("/{order_id}", response_model=OrderOut)
async def update_order(
    body: OrderUpdate,
    order: OrderDep,
    session: SessionDep,
):
    patch = body.model_dump(exclude_unset=True)
    await svc_update_meta(
        session,
        order,
        comments=patch.get("comments"),
        is_done=patch.get("is_done"),
        _comments_set=("comments" in patch),
    )
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


@order_router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order: OrderDep,
    session: SessionDep,
):
    """Cancel/delete an order. Frees the table; recomputes shift if was paid."""
    await svc_delete_order(session, order)
    await session.commit()


# ===== Items inside order =====

@order_router.post("/{order_id}/items", response_model=OrderOut)
async def add_order_items(
    body: OrderItemsAdd,
    order: OrderDep,
    session: SessionDep,
):
    await svc_add_items(session, order, [i.model_dump() for i in body.items])
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


@order_router.patch("/order-items/{item_id}", response_model=OrderOut)
async def update_order_item(
    body: OrderItemUpdate,
    user: CurrentUser,
    session: SessionDep,
    item_id: Annotated[str, Path()],
):
    item, order = await get_order_item_for_user(item_id=item_id, user=user, session=session)
    patch = body.model_dump(exclude_unset=True)

    await svc_update_item(
        session,
        order,
        item,
        title=patch.get("title"),
        price=patch.get("price"),
        quantity=patch.get("quantity"),
        comment=patch.get("comment"),
        served=patch.get("served"),
        _comment_set=("comment" in patch),
    )
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


@order_router.delete("/order-items/{item_id}", response_model=OrderOut)
async def delete_order_item(
    user: CurrentUser,
    session: SessionDep,
    item_id: Annotated[str, Path()],
):
    item, order = await get_order_item_for_user(item_id=item_id, user=user, session=session)
    await svc_remove_item(session, order, item)
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


# ===== Move / Pay =====

@order_router.post("/{order_id}/move", response_model=OrderOut)
async def move_order(
    body: OrderMove,
    order: OrderDep,
    session: SessionDep,
):
    """Move order to another table (or detach with table_id=null)."""
    await svc_move_order(session, order, body.table_id)
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


@order_router.post("/{order_id}/pay", response_model=OrderOut)
async def pay_order(
    body: OrderPay,
    order: OrderDep,
    session: SessionDep,
):
    await svc_pay_order(session, order, tips=body.tips)
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


@order_router.post("/{order_id}/reopen", response_model=OrderOut)
async def reopen_order(
    order: OrderDep,
    session: SessionDep,
    user: CurrentUser,
):
    """
    Return a paid order back to the active state. Allowed only for the shift
    owner, only while the original shift is still open, and only if the
    original table (if any) is not currently held by another order.
    """
    await svc_reopen_order(session, order, user_id=user.id)
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order


@order_router.patch("/{order_id}/edit", response_model=OrderOut)
async def edit_paid_order(
    body: OrderEdit,
    order: OrderDep,
    session: SessionDep,
    user: CurrentUser,
):
    """
    Edit a paid order's items, tips, or comments. The order stays paid;
    only the data is corrected. Allowed only for the shift owner while
    the order's shift is still open.
    """
    await svc_edit_paid_order(
        session, order,
        user_id=user.id,
        items=[i.model_dump() for i in body.items] if body.items is not None else None,
        tips=body.tips,
        comments=body.comments,
        guests_count=body.guests_count,
    )
    await session.commit()
    await session.refresh(order, attribute_names=["items"])
    return order
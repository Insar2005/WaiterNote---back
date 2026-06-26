"""
Order business logic: create, modify items, pay, cancel.

All functions accept a session and DO NOT commit. Caller commits.
This keeps multi-step operations atomic (e.g. pay_order recomputes shift aggregates
in the same transaction).
"""
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Order, OrderItem, Shift, Table, Hall, MenuItem
from services.shifts import recompute_aggregates as recompute_shift_aggregates
from utils.time import utc_ts


# =========================
# Helpers
# =========================

async def _load_order_with_items(
    session: AsyncSession,
    order_id: str,
) -> Order | None:
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _detach_order_from_table(
    session: AsyncSession,
    order: Order,
) -> None:
    """Clear Table.order_id and reset status to 'free' if this order was attached.
    Idempotent: safe to call multiple times."""
    if order.table_id is None:
        return
    table = await session.get(Table, order.table_id)
    if table is not None and table.order_id == order.id:
        table.order_id = None
        table.status = "free"


async def _attach_order_to_table(
    session: AsyncSession,
    order: Order,
    table: Table,
    has_items: bool,
) -> None:
    """Set Table.order_id and update status."""
    table.order_id = order.id
    # waiting = есть стол с заказом, но без позиций; occupied = с позициями
    table.status = "occupied" if has_items else "waiting"


def _recompute_order_total(order: Order) -> None:
    """Sum of OrderItem.total_price over loaded items."""
    order.total_price = round(
        sum(float(i.total_price) for i in order.items),
        2,
    )


def _item_total(price: float, quantity: int) -> float:
    return round(float(price) * int(quantity), 2)


# =========================
# Create order
# =========================

async def create_order(
    session: AsyncSession,
    *,
    order_id: str,
    shift: Shift,
    table_id: str | None,
    items: Iterable[dict],
    comments: str | None,
    guests_count: int = 1,
) -> Order:
    """Same as before plus an optional `guests_count` (1..10). Each
    raw item dict may carry a `guest` field (1..guests_count); items
    without one default to guest=1. The Pydantic OrderCreate validates
    the range/cross-consistency before we get here, so the values are
    already known-good — but legacy callers may still hit defaults."""
    """
    Create an order and (optionally) attach to a table. Atomic.

    items: each dict must contain id (nanoid), title, price, quantity.
           menu_item_id and comment are optional.
    """
    if shift.is_closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot create order in a closed shift",
        )

    if await session.get(Order, order_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="order with this id already exists",
        )

    table_obj: Table | None = None
    hall_obj: Hall | None = None
    table_number: int | None = None
    hall_id: str | None = None
    hall_name: str | None = None

    if table_id is not None:
        table_obj = await session.get(Table, table_id)
        if table_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="table not found",
            )
        # busy?
        if table_obj.order_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="table already has an active order",
            )

        hall_obj = await session.get(Hall, table_obj.hall_id)
        if hall_obj is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "hall missing")

        # workplace must match shift's workplace
        if hall_obj.workplace_id != shift.workplace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="table belongs to a different workplace",
            )

        table_number = table_obj.number
        hall_id = hall_obj.id
        hall_name = hall_obj.name

    order = Order(
    id=order_id,
    shift_id=shift.id,
    hall_id=hall_id,
    table_id=table_id,
    table_number=table_number,
    hall_name=hall_name,
    comments=comments,
    is_paid=False,
    is_done=False,
    tips=0.0,
    total_price=0.0,
    closed_at=None,
    guests_count=guests_count,
)
    session.add(order)

    items_list = list(items)
    for raw in items_list:
        oi = OrderItem(
            id=raw["id"],
            order_id=order.id,
            menu_item_id=raw.get("menu_item_id"),
            title=raw["title"],
            price=float(raw["price"]),
            quantity=int(raw["quantity"]),
            total_price=_item_total(raw["price"], raw["quantity"]),
            comment=raw.get("comment"),
            guest=int(raw.get("guest", 1)),
        )
        session.add(oi)

    # need order.items populated for total recompute
    await session.flush()
    await session.refresh(order, attribute_names=["items"])
    _recompute_order_total(order)

    if table_obj is not None:
        await _attach_order_to_table(session, order, table_obj, has_items=bool(items_list))

    return order


# =========================
# Modify items
# =========================

def _ensure_editable(order: Order) -> None:
    if order.is_paid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot modify a paid order",
        )


async def add_items(
    session: AsyncSession,
    order: Order,
    items: Iterable[dict],
) -> Order:
    _ensure_editable(order)
    items_list = list(items)
    for raw in items_list:
        if await session.get(OrderItem, raw["id"]) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"order item id {raw['id']} already exists",
            )
        oi = OrderItem(
            id=raw["id"],
            order_id=order.id,
            menu_item_id=raw.get("menu_item_id"),
            title=raw["title"],
            price=float(raw["price"]),
            quantity=int(raw["quantity"]),
            total_price=_item_total(raw["price"], raw["quantity"]),
            comment=raw.get("comment"),
            guest=int(raw.get("guest", 1)),
        )
        session.add(oi)

    await session.flush()
    await session.refresh(order, attribute_names=["items"])
    _recompute_order_total(order)

    # If this is the first batch of items on a 'waiting' table, mark occupied
    if order.table_id is not None and order.items:
        table = await session.get(Table, order.table_id)
        if table is not None and table.status == "waiting":
            table.status = "occupied"

    return order


async def update_item(
    session: AsyncSession,
    order: Order,
    item: OrderItem,
    *,
    price: float | None = None,
    quantity: int | None = None,
    comment: str | None = None,
    title: str | None = None,
    served: bool | None = None,
    _comment_set: bool = False,
) -> Order:
    """Caller passes only fields that should change.
    `_comment_set` distinguishes 'omit' from 'set to null' for comment.

    Note: `served` is allowed on paid orders too — toggling whether a dish
    has been carried to the table is purely informational and doesn't change
    the bill. All other fields require the order to still be editable.
    """
    # If the request touches anything other than `served`, enforce editability.
    touches_money = (
        title is not None
        or price is not None
        or quantity is not None
        or _comment_set
    )
    if touches_money:
        _ensure_editable(order)

    if title is not None:
        item.title = title
    if price is not None:
        item.price = float(price)
    if quantity is not None:
        item.quantity = int(quantity)
    if _comment_set:
        item.comment = comment
    if served is not None:
        item.served = bool(served)
    item.total_price = _item_total(item.price, item.quantity)

    await session.flush()
    await session.refresh(order, attribute_names=["items"])
    _recompute_order_total(order)
    return order


async def remove_item(
    session: AsyncSession,
    order: Order,
    item: OrderItem,
) -> Order:
    _ensure_editable(order)
    await session.delete(item)
    await session.flush()
    await session.refresh(order, attribute_names=["items"])
    _recompute_order_total(order)

    # If we removed the last item and order is on a table, drop status to 'waiting'
    if order.table_id is not None and not order.items:
        table = await session.get(Table, order.table_id)
        if table is not None and table.status == "occupied":
            table.status = "waiting"

    return order


async def update_order_meta(
    session: AsyncSession,
    order: Order,
    *,
    comments: str | None = None,
    is_done: bool | None = None,
    _comments_set: bool = False,
) -> Order:
    """Update order-level metadata (not items). is_done is a 'kitchen ready' flag."""
    _ensure_editable(order)
    if _comments_set:
        order.comments = comments
    if is_done is not None:
        order.is_done = is_done
    return order


# =========================
# Move order to another table
# =========================

async def move_order_to_table(
    session: AsyncSession,
    order: Order,
    new_table_id: str | None,
) -> Order:
    """
    Move an active (unpaid) order to another table, or detach (new_table_id=None).
    Updates table snapshots.
    """
    _ensure_editable(order)

    if new_table_id == order.table_id:
        return order  # no-op

    # Detach from current table
    await _detach_order_from_table(session, order)

    if new_table_id is None:
        order.table_id = None
        order.hall_id = None
        order.table_number = None
        order.hall_name = None
        return order

    new_table = await session.get(Table, new_table_id)
    if new_table is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "target table not found")
    if new_table.order_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "target table already has an active order",
        )

    new_hall = await session.get(Hall, new_table.hall_id)
    if new_hall is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "target hall missing")

    # Verify same workplace as the shift
    shift = await session.get(Shift, order.shift_id)
    if shift is None or new_hall.workplace_id != shift.workplace_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "target table belongs to a different workplace",
        )

    order.table_id = new_table.id
    order.hall_id = new_hall.id
    order.table_number = new_table.number
    order.hall_name = new_hall.name

    await _attach_order_to_table(
        session, order, new_table,
        has_items=bool(order.items),
    )
    return order


# =========================
# Pay order
# =========================

async def pay_order(
    session: AsyncSession,
    order: Order,
    *,
    tips: float,
) -> Order:
    """
    Mark order as paid + close it + free the table + recompute shift aggregates.
    All in one transaction (commit by caller).
    """
    if order.is_paid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="order is already paid",
        )
    if not order.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot pay an empty order",
        )

    order.tips = float(tips)
    order.is_paid = True
    order.is_done = True  # paid implies done
    order.closed_at = utc_ts()

    await _detach_order_from_table(session, order)

    # Recompute shift aggregates (paid orders are the source of truth)
    shift = await session.get(Shift, order.shift_id)
    if shift is not None:
        await recompute_shift_aggregates(session, shift)

    return order


# =========================
# Reopen / edit paid orders
# =========================

async def reopen_order(
    session: AsyncSession,
    order: Order,
    user_id: int,
) -> Order:
    """
    Reopen a paid order so the waiter can continue serving the same guest.

    Constraints:
      - order must currently be paid
      - shift must be open AND owned by `user_id`
      - the original table (if any) must not currently be held by another order

    Side effects:
      - is_paid/is_done = False, closed_at = 0, tips = 0
      - re-attaches table (status = occupied/waiting depending on items)
      - recomputes shift aggregates (the order leaves the paid set automatically)
    """
    if not order.is_paid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="order is not paid",
        )

    shift = await session.get(Shift, order.shift_id)
    if shift is None or shift.end_time is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot reopen orders from a closed shift",
        )
    if shift.opened_by_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the shift owner can reopen orders",
        )

    if order.table_id is not None:
        table = await session.get(Table, order.table_id)
        if table is not None and table.order_id is not None and table.order_id != order.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="table is currently held by another order",
            )

    order.is_paid = False
    order.is_done = False
    order.closed_at = 0
    order.tips = 0.0

    if order.table_id is not None:
        table = await session.get(Table, order.table_id)
        if table is not None:
            await _attach_order_to_table(session, order, table, has_items=bool(order.items))

    await recompute_shift_aggregates(session, shift)
    return order


async def edit_paid_order(
    session: AsyncSession,
    order: Order,
    user_id: int,
    *,
    items: list[dict] | None = None,
    tips: float | None = None,
    comments: str | None = None,
    guests_count: int | None = None,
) -> Order:
    """
    Edit a paid order's items, tips, or comments. The order stays paid;
    the table stays free; only the data is corrected.

    `items`, if provided, fully replaces the existing item list.
    Each dict should have: id?, menu_item_id?, title, price, quantity, comment?

    Constraints:
      - order must be paid
      - shift must be open AND owned by `user_id` (no edits on past shifts)
    """
    if not order.is_paid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="order is not paid",
        )

    shift = await session.get(Shift, order.shift_id)
    if shift is None or shift.end_time is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot edit orders from a closed shift",
        )
    if shift.opened_by_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the shift owner can edit orders",
        )

    # Replace items list if provided
    if items is not None:
        # Drop old items
        for old_item in list(order.items):
            await session.delete(old_item)
        order.items.clear()
        # Insert new (caller is responsible for fresh nanoid IDs)
        for raw in items:
            item_id = raw.get("id")
            if not item_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="each item must have an `id` (nanoid)",
                )
            qty = max(1, int(raw.get("quantity", 1)))
            price = float(raw.get("price", 0))
            order.items.append(
                OrderItem(
                    id=item_id,
                    order_id=order.id,
                    menu_item_id=raw.get("menu_item_id"),
                    title=raw.get("title", "—"),
                    price=price,
                    quantity=qty,
                    total_price=_item_total(price, qty),
                    comment=raw.get("comment"),
                    guest=int(raw.get("guest", 1)),
                )
            )
        _recompute_order_total(order)

    if guests_count is not None:
        order.guests_count = int(guests_count)
    if tips is not None:
        order.tips = float(tips)
    if comments is not None:
        order.comments = comments

    await recompute_shift_aggregates(session, shift)
    return order


# Delete / cancel order
# =========================

async def delete_order(
    session: AsyncSession,
    order: Order,
) -> None:
    """
    Hard delete. Use for cancelling an unpaid order or fixing mistakes.
    If the order was paid, shift aggregates are recomputed afterwards.
    """
    was_paid = order.is_paid
    shift_id = order.shift_id

    await _detach_order_from_table(session, order)
    await session.delete(order)
    await session.flush()

    if was_paid:
        shift = await session.get(Shift, shift_id)
        if shift is not None:
            await recompute_shift_aggregates(session, shift)
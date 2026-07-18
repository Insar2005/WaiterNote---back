from typing import Optional
from pydantic import Field, model_validator

from .common import APIModel, NanoID


# Guest split limits — match the UI dialog. 1 = single bill ("Один чек");
# 2..10 = per-guest split. Kept here so all guest-related schemas share
# the same validator constants.
MIN_GUESTS = 1
MAX_GUESTS = 10


# ===== OrderItem =====

class OrderItemDraft(APIModel):
    """Item inside a new order or a batch-add."""
    id: NanoID
    menu_item_id: Optional[NanoID] = None
    title: str = Field(min_length=1, max_length=150)
    price: float = Field(ge=0)
    quantity: int = Field(ge=1)
    comment: Optional[str] = Field(default=None, max_length=2000)
    # Guest index this item belongs to. 1 = single-bill behaviour (or
    # guest #1 in a split). Upper bound enforced at the Order level —
    # we don't know guests_count here, so the order-level validator
    # below cross-checks it.
    guest: int = Field(default=1, ge=1, le=MAX_GUESTS)


class OrderItemUpdate(APIModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=150)
    price: Optional[float] = Field(default=None, ge=0)
    quantity: Optional[int] = Field(default=None, ge=1)
    comment: Optional[str] = Field(default=None, max_length=2000)
    served: Optional[bool] = None


class OrderItemOut(APIModel):
    id: str
    order_id: str
    menu_item_id: Optional[str]
    title: str
    price: float
    quantity: int
    total_price: float
    comment: Optional[str]
    served: bool
    # Always returned. Defaults to 1 for legacy orders (per ALTER TABLE
    # DEFAULT). The client groups items by this number in the cart, in
    # the finalized order view, and in history.
    guest: int


# ===== Order =====

class OrderCreate(APIModel):
    """POST /shifts/{sid}/orders body."""
    id: NanoID
    table_id: Optional[NanoID] = None
    comments: Optional[str] = Field(default=None, max_length=2000)
    # Per-table guest split. Optional in the wire format for backward
    # compat with older clients that don't send it — defaults to 1.
    guests_count: int = Field(default=1, ge=MIN_GUESTS, le=MAX_GUESTS)
    items: list[OrderItemDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_item_guests_in_range(self) -> "OrderCreate":
        """Each item's `guest` must fit inside this order's guests_count.
        The UI guarantees this, but we validate so a buggy client can't
        store inconsistent data."""
        for item in self.items:
            if item.guest > self.guests_count:
                raise ValueError(
                    f"item.guest={item.guest} exceeds guests_count={self.guests_count}"
                )
        return self


class OrderUpdate(APIModel):
    """PATCH /orders/{id} — order-level fields only (not items)."""
    comments: Optional[str] = Field(default=None, max_length=2000)
    is_done: Optional[bool] = None


class OrderItemsAdd(APIModel):
    """POST /orders/{id}/items — append items (each carries its own `guest`)."""
    items: list[OrderItemDraft] = Field(min_length=1)


class OrderPay(APIModel):
    """POST /orders/{id}/pay"""
    tips: float = Field(default=0.0, ge=0)


class OrderMove(APIModel):
    """POST /orders/{id}/move — change table or detach (table_id=null)."""
    table_id: Optional[NanoID] = None


class OrderEdit(APIModel):
    """
    PATCH /orders/{id}/edit — modify a paid order (in the current open shift).

    Every field is optional; passing it edits that aspect, omitting it
    leaves it as is. Two important cases the frontend relies on:
      • `tips` only — quick edit from the history screen for a forgotten
        tip; the items list must NOT be touched.
      • `items` + `guests_count` — full re-edit; guests_count must come
        with items so the new lines can reference valid guest numbers.
    """
    items: Optional[list[OrderItemDraft]] = None
    tips: Optional[float] = Field(default=None, ge=0)
    comments: Optional[str] = Field(default=None, max_length=2000)
    guests_count: Optional[int] = Field(default=None, ge=MIN_GUESTS, le=MAX_GUESTS)

    @model_validator(mode="after")
    def _check_item_guests_in_range(self) -> "OrderEdit":
        """If items are being replaced and guests_count is also set,
        verify they're consistent. If items are replaced WITHOUT a new
        guests_count, the service layer uses the existing order's count
        (we can't access it here)."""
        if self.items is not None and self.guests_count is not None:
            for item in self.items:
                if item.guest > self.guests_count:
                    raise ValueError(
                        f"item.guest={item.guest} exceeds guests_count={self.guests_count}"
                    )
        return self


class OrderOut(APIModel):
    id: str
    shift_id: str
    hall_id: Optional[str]
    table_id: Optional[str]
    table_number: Optional[int]
    hall_name: Optional[str]
    comments: Optional[str]
    created_at: int
    updated_at: int
    closed_at: Optional[int]
    tips: float
    total_price: float
    is_paid: bool
    is_done: bool
    # Number of guests on the order. Default 1 for legacy orders.
    guests_count: int
    items: list[OrderItemOut] = []
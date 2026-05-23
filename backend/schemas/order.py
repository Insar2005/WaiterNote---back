from typing import Optional
from pydantic import Field

from .common import APIModel, NanoID


# ===== OrderItem =====

class OrderItemDraft(APIModel):
    """Item inside a new order or batch-add."""
    id: NanoID
    menu_item_id: Optional[NanoID] = None
    title: str = Field(min_length=1, max_length=150)
    price: float = Field(ge=0)
    quantity: int = Field(ge=1)
    comment: Optional[str] = Field(default=None, max_length=2000)


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


# ===== Order =====

class OrderCreate(APIModel):
    """POST /shifts/{sid}/orders"""
    id: NanoID
    table_id: Optional[NanoID] = None
    comments: Optional[str] = Field(default=None, max_length=2000)
    items: list[OrderItemDraft] = Field(default_factory=list)


class OrderUpdate(APIModel):
    """PATCH /orders/{id} — order-level fields only (not items)."""
    comments: Optional[str] = Field(default=None, max_length=2000)
    is_done: Optional[bool] = None


class OrderItemsAdd(APIModel):
    """POST /orders/{id}/items"""
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

    Any field may be omitted to leave it untouched. Passing `items` performs
    a full replacement of the line items.
    """
    items: Optional[list[OrderItemDraft]] = None
    tips: Optional[float] = Field(default=None, ge=0)
    comments: Optional[str] = Field(default=None, max_length=2000)


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
    items: list[OrderItemOut] = []
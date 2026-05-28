from typing import Optional, Dict
from pydantic import Field

from .common import APIModel, NanoID


# ===== TablePosition =====

class TablePositionBase(APIModel):
    """Position of a single table inside a layout, keyed by table number."""
    table_number: int = Field(ge=1)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: int = Field(ge=10, le=10000)
    height: int = Field(ge=10, le=10000)
    rotation: int = Field(ge=-360, le=360)
    border_radius: int = Field(ge=0, le=500)


class TablePositionOut(TablePositionBase):
    id: str
    layout_id: str


# ===== HallLayout =====

class HallLayoutBase(APIModel):
    name: str = Field(min_length=1, max_length=100)


class HallLayoutCreate(HallLayoutBase):
    id: NanoID


class HallLayoutUpdate(APIModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)


class HallLayoutOut(HallLayoutBase):
    id: str
    hall_id: str
    created_at: int
    updated_at: int
    positions: list[TablePositionOut] = []


# ===== Apply =====

class LayoutApplyBody(APIModel):
    """
    Options for applying a layout to a hall.

    `delete_extras`: when true, tables in the hall whose number is NOT in
    the layout get removed (unless they have an active order — those are
    always preserved, see `kept_extras` in the response).

    `new_table_ids`: caller-supplied IDs for newly-created tables, keyed
    by their `table_number`. Lets the client generate stable nanoids on
    its side, matching the pattern used for other create endpoints.
    """
    delete_extras: bool = False
    new_table_ids: Dict[int, NanoID] = Field(default_factory=dict)


class KeptExtraOut(APIModel):
    """Table that couldn't be removed during apply (had an active order)."""
    id: str
    number: int
    reason: str  # currently always "active_order"


class LayoutApplyResult(APIModel):
    moved: list[str]
    created: list[str]
    kept_extras: list[KeptExtraOut]
    deleted_extras: list[str]
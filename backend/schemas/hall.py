from typing import Optional, Literal
from pydantic import Field

from .common import APIModel, NanoID


# ===== Table =====

TableStatusLiteral = Literal["free", "waiting", "occupied", "reserved"]


class TableBase(APIModel):
    number: int = Field(ge=1)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: int = Field(ge=10, le=10000)
    height: int = Field(ge=10, le=10000)
    rotation: int = Field(ge=-360, le=360)
    border_radius: int = Field(ge=0, le=500)


class TableCreate(TableBase):
    id: NanoID


class TableUpdate(APIModel):
    number: Optional[int] = Field(default=None, ge=1)
    x: Optional[float] = Field(default=None, ge=0)
    y: Optional[float] = Field(default=None, ge=0)
    width: Optional[int] = Field(default=None, ge=10, le=10000)
    height: Optional[int] = Field(default=None, ge=10, le=10000)
    rotation: Optional[int] = Field(default=None, ge=-360, le=360)
    border_radius: Optional[int] = Field(default=None, ge=0, le=500)
    status: Optional[TableStatusLiteral] = None


class TableOut(TableBase):
    id: str
    hall_id: str
    order_id: Optional[str]
    status: str  # TableStatusLiteral, but loose for ORM


# ===== Hall =====

class HallBase(APIModel):
    name: str = Field(min_length=1, max_length=100)
    width: int = Field(ge=100, le=10000)
    height: int = Field(ge=100, le=10000)
    scale: float = Field(gt=0, le=10)


class HallCreate(HallBase):
    id: NanoID


class HallUpdate(APIModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    width: Optional[int] = Field(default=None, ge=100, le=10000)
    height: Optional[int] = Field(default=None, ge=100, le=10000)
    scale: Optional[float] = Field(default=None, gt=0, le=10)


class HallOut(HallBase):
    id: str
    workplace_id: str
    position: int
    tables: list[TableOut] = []
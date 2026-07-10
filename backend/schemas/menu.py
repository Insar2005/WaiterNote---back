from typing import Optional
from pydantic import Field

from .common import APIModel, NanoID


# ===== Menu Item =====

class MenuItemBase(APIModel):
    title: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=2000)
    portion: Optional[str] = Field(default=None, max_length=50)
    price: float = Field(ge=0)
    comment_chips: list[str] = Field(default_factory=list)


class MenuItemCreate(MenuItemBase):
    id: NanoID


class MenuItemUpdate(APIModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=2000)
    portion: Optional[str] = Field(default=None, max_length=50)
    price: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    category_id: Optional[NanoID] = None
    comment_chips: Optional[list[str]] = None


class MenuItemOut(MenuItemBase):
    id: str
    category_id: str
    position: int
    is_active: bool


# ===== Menu Category =====

class MenuCategoryBase(APIModel):
    title: str = Field(min_length=1, max_length=100)
    parent_id: Optional[NanoID] = None


class MenuCategoryCreate(MenuCategoryBase):
    id: NanoID


class MenuCategoryUpdate(APIModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    parent_id: Optional[NanoID] = None  # null → сделать корневой


class MenuCategoryOut(MenuCategoryBase):
    id: str
    workplace_id: str
    position: int
    is_active: bool
    items: list[MenuItemOut] = []
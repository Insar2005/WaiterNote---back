# backend/schemas/common.py
from typing import Annotated
from pydantic import BaseModel, ConfigDict, AfterValidator

from utils.ids import is_valid_id


def _validate_id(v: str) -> str:
    if not is_valid_id(v):
        raise ValueError("invalid id format (expected nanoid 21 chars)")
    return v


# Use as: id: NanoID
NanoID = Annotated[str, AfterValidator(_validate_id)]


class APIModel(BaseModel):
    """Base for all DTOs. ORM-friendly + strict by default."""
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        extra="forbid",
    )


class IDOut(APIModel):
    """Generic response when only id is returned."""
    id: str


class ReorderRequest(APIModel):
    """Generic body for reorder endpoints: list of IDs in desired order."""
    ids: list[NanoID]
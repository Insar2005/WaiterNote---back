from typing import Optional, Literal
from pydantic import Field, model_validator

from .common import APIModel, NanoID


NoteScopeLiteral = Literal["global", "workplace", "shift"]


class NoteCreate(APIModel):
    id: NanoID
    scope: NoteScopeLiteral
    workplace_id: Optional[NanoID] = None
    shift_id: Optional[NanoID] = None
    header: str = Field(min_length=1, max_length=255)
    content: Optional[str] = Field(default=None, max_length=20000)
    pinned: bool = False

    @model_validator(mode="after")
    def _check_scope_consistency(self) -> "NoteCreate":
        if self.scope == "global":
            if self.workplace_id is not None or self.shift_id is not None:
                raise ValueError("global notes must not have workplace_id or shift_id")
        elif self.scope == "workplace":
            if self.workplace_id is None:
                raise ValueError("workplace notes require workplace_id")
            if self.shift_id is not None:
                raise ValueError("workplace notes must not have shift_id")
        elif self.scope == "shift":
            if self.shift_id is None:
                raise ValueError("shift notes require shift_id")
        return self


class NoteUpdate(APIModel):
    """Update note content/state. Scope and bindings are immutable —
    create a new note in another scope if needed."""
    header: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = Field(default=None, max_length=20000)
    pinned: Optional[bool] = None
    is_archived: Optional[bool] = None


class NoteOut(APIModel):
    id: str
    user_id: int
    scope: str
    workplace_id: Optional[str]
    shift_id: Optional[str]
    header: str
    content: Optional[str]
    pinned: bool
    is_archived: bool
    created_at: int
    updated_at: int
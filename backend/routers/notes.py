from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select

from models import Notes, Workplace, WorkplaceMember, Shift
from deps import SessionDep, CurrentUser
from schemas.note import NoteCreate, NoteUpdate, NoteOut


router = APIRouter(prefix="/notes", tags=["notes"])


# ===== Access helper =====

async def get_note_for_user(
    note_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Notes:
    """Notes are private to the user."""
    note = await session.get(Notes, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    return note


NoteDep = Annotated[Notes, Depends(get_note_for_user)]


# ===== Cross-checks for create =====

async def _verify_scope_refs(
    session,
    user,
    *,
    workplace_id: str | None,
    shift_id: str | None,
) -> None:
    """Verify the user has access to referenced workplace/shift."""
    if workplace_id is not None:
        access = await session.scalar(
            select(WorkplaceMember.id).where(
                WorkplaceMember.workplace_id == workplace_id,
                WorkplaceMember.user_id == user.id,
            )
        )
        if not access:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "workplace not found or access denied",
            )

    if shift_id is not None:
        # Verify shift exists and user has access via workplace membership
        stmt = (
            select(Shift)
            .join(Workplace, Workplace.id == Shift.workplace_id)
            .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
            .where(
                Shift.id == shift_id,
                WorkplaceMember.user_id == user.id,
            )
        )
        shift = (await session.execute(stmt)).scalar_one_or_none()
        if shift is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "shift not found or access denied",
            )


# ===== Endpoints =====

@router.get("", response_model=list[NoteOut])
async def list_notes(
    user: CurrentUser,
    session: SessionDep,
    scope: Optional[str] = Query(None, pattern="^(global|workplace|shift)$"),
    workplace_id: Optional[str] = None,
    shift_id: Optional[str] = None,
    include_archived: bool = False,
    pinned_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    List user's notes with filters. Default order: pinned first, then updated_at desc.
    """
    stmt = select(Notes).where(Notes.user_id == user.id)

    if scope is not None:
        stmt = stmt.where(Notes.scope == scope)
    if workplace_id is not None:
        stmt = stmt.where(Notes.workplace_id == workplace_id)
    if shift_id is not None:
        stmt = stmt.where(Notes.shift_id == shift_id)
    if not include_archived:
        stmt = stmt.where(Notes.is_archived.is_(False))
    if pinned_only:
        stmt = stmt.where(Notes.pinned.is_(True))

    stmt = (
        stmt.order_by(Notes.pinned.desc(), Notes.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(
    body: NoteCreate,
    user: CurrentUser,
    session: SessionDep,
):
    if await session.get(Notes, body.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "note id already exists")

    await _verify_scope_refs(
        session, user,
        workplace_id=body.workplace_id,
        shift_id=body.shift_id,
    )

    note = Notes(
        id=body.id,
        user_id=user.id,
        scope=body.scope,
        workplace_id=body.workplace_id,
        shift_id=body.shift_id,
        header=body.header,
        content=body.content,
        pinned=body.pinned,
        is_archived=False,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(note: NoteDep):
    return note


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(
    body: NoteUpdate,
    note: NoteDep,
    session: SessionDep,
):
    patch = body.model_dump(exclude_unset=True)
    for k, v in patch.items():
        setattr(note, k, v)
    await session.commit()
    await session.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note: NoteDep,
    session: SessionDep,
):
    await session.delete(note)
    await session.commit()
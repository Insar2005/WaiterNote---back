from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select

from models import Reminder
from deps import SessionDep, CurrentUser
from schemas.reminder import ReminderCreate, ReminderUpdate, ReminderOut


router = APIRouter(prefix="/reminders", tags=["reminders"])


# ===== Access helper =====

async def get_reminder_for_user(
    reminder_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Reminder:
    """Reminders are personal; only the owner can read or modify."""
    r = await session.get(Reminder, reminder_id)
    if r is None or r.user_id != user.id:
        # Same 404 message for not-found vs not-owner — don't leak the
        # existence of other users' reminders. Matches the notes router.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    return r


ReminderDep = Annotated[Reminder, Depends(get_reminder_for_user)]


# ===== Endpoints =====

@router.get("", response_model=list[ReminderOut])
async def list_reminders(
    user: CurrentUser,
    session: SessionDep,
    include_done: bool = Query(True),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    List current user's reminders sorted by remind_at ASC.

    By default both done and pending reminders are returned — the UI shows
    done items in their own collapsed group. Pass include_done=false to
    hide them entirely (e.g. for a "pending only" widget).
    """
    stmt = select(Reminder).where(Reminder.user_id == user.id)
    if not include_done:
        stmt = stmt.where(Reminder.is_done.is_(False))
    stmt = stmt.order_by(Reminder.remind_at.asc()).limit(limit).offset(offset)

    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    body: ReminderCreate,
    user: CurrentUser,
    session: SessionDep,
):
    """
    Create a reminder. Client supplies the id (nanoid). Duplicate id → 409.
    The bot picks this up on the next worker tick if remind_at is near.
    """
    if await session.get(Reminder, body.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "reminder id already exists")

    reminder = Reminder(
        id=body.id,
        user_id=user.id,
        text=body.text.strip(),
        remind_at=body.remind_at,
        lead_minutes=body.lead_minutes,
        is_done=False,
        notified_at=None,
    )
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


@router.patch("/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    body: ReminderUpdate,
    reminder: ReminderDep,
    session: SessionDep,
):
    """
    Update a reminder. Any subset of fields. Important: when the user
    changes remind_at OR lead_minutes we reset notified_at to NULL — the
    bot must fire again under the new schedule (matches the spec §1.2).

    Setting is_done=True is fine even if notified_at is already set; the
    worker just won't pick it up next time. We don't auto-uncheck on
    schedule change either — the user controls is_done explicitly.
    """
    patch = body.model_dump(exclude_unset=True)

    # Detect schedule change BEFORE applying patch, so we know whether to
    # clear notified_at. Using "is in patch" rather than "value differs"
    # so an explicit "set to current value" still resets — that's the
    # least surprising behaviour and matches the spec wording.
    schedule_changed = "remind_at" in patch or "lead_minutes" in patch

    for k, v in patch.items():
        if k == "text" and isinstance(v, str):
            v = v.strip()
        setattr(reminder, k, v)

    if schedule_changed:
        reminder.notified_at = None

    await session.commit()
    await session.refresh(reminder)
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder: ReminderDep,
    session: SessionDep,
):
    """Hard delete. No undo — the UI confirms before calling this."""
    await session.delete(reminder)
    await session.commit()
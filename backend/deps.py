from typing import Annotated, AsyncGenerator

from fastapi import Depends, Header, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import async_session, User, Workplace, WorkplaceMember
from auth import parse_and_validate_init_data, InitDataParseError
from config import get_settings, Settings
from utils.time import utc_ts


# ===== DB =====

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ===== Current user =====

async def get_current_user(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    x_init_data: Annotated[str | None, Header(alias="X-Init-Data")] = None,
) -> User:
    """
    Validates Telegram initData from X-Init-Data header, finds-or-creates user.
    """
    if not x_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Init-Data header required",
        )

    try:
        tg_user = parse_and_validate_init_data(
            x_init_data,
            settings.BOT_TOKEN,
            settings.INIT_DATA_TTL,
        )
    except InitDataParseError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid initData: {e}",
        ) from e

    tg_id = int(tg_user["id"])

    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            tg_id=tg_id,
            username=tg_user.get("username"),
            language=(tg_user.get("language_code") or "ru")[:10],
        )
        session.add(user)
        await session.flush()  # need user.id for downstream

    # Cheap heartbeat + username sync
    user.last_online_at = utc_ts()
    new_username = tg_user.get("username")
    if new_username and new_username != user.username:
        user.username = new_username

    await session.commit()
    await session.refresh(user)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ===== Workplace access =====

async def get_workplace_for_user(
    workplace_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Workplace:
    """
    Verify the current user has access to this workplace (owner or member).
    Use this in path-parameterized endpoints: /workplaces/{workplace_id}/...
    """
    stmt = (
        select(Workplace)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            Workplace.id == workplace_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    result = await session.execute(stmt)
    workplace = result.scalar_one_or_none()

    if workplace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="workplace not found or access denied",
        )
    return workplace


WorkplaceDep = Annotated[Workplace, Depends(get_workplace_for_user)]


async def require_workplace_owner(
    workplace: WorkplaceDep,
    user: CurrentUser,
) -> Workplace:
    """For destructive ops (delete, archive)."""
    if workplace.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="owner access required",
        )
    return workplace


WorkplaceOwnerDep = Annotated[Workplace, Depends(require_workplace_owner)]
from fastapi import APIRouter

from deps import SessionDep, CurrentUser
from schemas.user import UserOut, UserUpdate

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def get_me(user: CurrentUser):
    """
    Returns current user (creates one on first call thanks to get_current_user).
    Frontend calls this on app start to get last_workplace_id and locale.
    """
    return user


@router.patch("", response_model=UserOut)
async def update_me(
    body: UserUpdate,
    user: CurrentUser,
    session: SessionDep,
):
    patch = body.model_dump(exclude_unset=True)
    for k, v in patch.items():
        setattr(user, k, v)
    await session.commit()
    await session.refresh(user)
    return user
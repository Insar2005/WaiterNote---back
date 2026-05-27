from fastapi import APIRouter

from deps import SessionDep, CurrentUser
from schemas.user import UserOut, UserUpdate, BotAccessOut
from services.telegram_bot import check_bot_can_message, get_bot_username

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def get_me(user: CurrentUser):
    """
    Returns current user (creates one on first call thanks to get_current_user).
    Frontend calls this on app start to get last_workplace_id and locale.
    """
    return user


@router.get("/bot-access", response_model=BotAccessOut)
async def get_bot_access(user: CurrentUser):
    """
    Probe whether our bot can write to this user. Calls the Telegram API
    on every request — there's no good way to cache "the user pressed
    /start", since they can block/unblock the bot any time.

    The frontend uses this to gate access to the app: if `status` is
    "blocked", we show an "open the bot" screen instead of the home page.
    "unreachable" gets a separate retry UI — we don't lock people out
    just because Telegram had a hiccup.
    """
    status = await check_bot_can_message(user.tg_id)
    username = await get_bot_username()
    return BotAccessOut(status=status, bot_username=username)


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
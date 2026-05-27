from typing import Literal, Optional
from pydantic import Field

from .common import APIModel


class UserOut(APIModel):
    id: int
    tg_id: int
    username: Optional[str]
    language: str
    timezone: str
    last_online_at: Optional[int]
    last_workplace_id: Optional[str]
    is_onboarding_completed: bool
    created_at: int
    updated_at: int


class UserUpdate(APIModel):
    language: Optional[str] = Field(default=None, min_length=2, max_length=10)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_onboarding_completed: Optional[bool] = None


class BotAccessOut(APIModel):
    """
    Result of probing whether the configured bot can message the current user.

    status:
      ok          — bot can write, app gate is open
      blocked     — user hasn't pressed /start (or blocked the bot); show
                    the "open the bot" gate screen
      unreachable — couldn't reach Telegram API to check; the client should
                    show a retry UI rather than guess.
    bot_username: bot @username for building the deep link, or None if
    we couldn't resolve it.
    """
    status: Literal["ok", "blocked", "unreachable"]
    bot_username: Optional[str] = None
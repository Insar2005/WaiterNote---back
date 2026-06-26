from typing import Optional
from pydantic import Field

from .common import APIModel, NanoID


# Allowed lead values match the UI preset list in the frontend
# (src/stores/reminders.js: LEAD_OPTIONS). Server-side we accept ANY
# non-negative int — the UI restricts to presets but we don't want to
# reject odd values from future client versions or scripted creates.


class ReminderCreate(APIModel):
    """POST /reminders body."""

    id: NanoID
    text: str = Field(min_length=1, max_length=255)
    # Unix seconds, UTC. The client computes this from its own clock
    # (Telegram WebApp doesn't expose a server clock). We don't enforce
    # remind_at > now — the user may create a "past" reminder and mark
    # it done immediately, or import historical data from elsewhere.
    remind_at: int = Field(ge=0)
    lead_minutes: int = Field(default=0, ge=0)


class ReminderUpdate(APIModel):
    """PATCH /reminders/{id} body — any subset of fields."""

    text: Optional[str] = Field(default=None, min_length=1, max_length=255)
    remind_at: Optional[int] = Field(default=None, ge=0)
    lead_minutes: Optional[int] = Field(default=None, ge=0)
    is_done: Optional[bool] = None


class ReminderOut(APIModel):
    """GET / response shape."""

    id: str
    user_id: int
    text: str
    remind_at: int
    lead_minutes: int
    is_done: bool
    # NULL while the reminder is pending; set by the bot worker after the
    # notification is sent. Exposed so the client can dim "already
    # notified" rows if it ever wants to.
    notified_at: Optional[int]
    created_at: int
    updated_at: int
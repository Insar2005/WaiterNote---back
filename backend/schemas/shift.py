from typing import Optional
from pydantic import Field

from .common import APIModel, NanoID


class ShiftOpen(APIModel):
    """Body for POST /workplaces/{wid}/shifts (open new shift)."""
    id: NanoID  # client-generated nanoid


class ShiftOut(APIModel):
    id: str
    workplace_id: str
    opened_by_user_id: int
    start_time: int
    is_closed: bool
    end_time: Optional[int]

    place_work_title: str
    currency: str
    service_percent: int
    shift_type: str
    pay_for_shift: float

    total_pay_for_shift: float
    total_tips: float
    total_cash_register: float
    order_count: int
    duration: int  # seconds; for open shifts this is 0 (compute live on client)
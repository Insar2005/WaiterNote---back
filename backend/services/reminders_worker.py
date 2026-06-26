"""
Reminders notification worker.

Background asyncio task that wakes up roughly once a minute, finds
reminders whose notify-time has arrived, and asks the Telegram bot to
send the user a message. After a successful send the row's
`notified_at` is set so the same reminder won't fire twice.

Lifecycle: started from the FastAPI `lifespan` context (see main.py).
Cancelled cleanly on shutdown.

Why a loop in-process and not a separate cron/queue service:
  - We're already a single managed FastAPI service on Railway; spinning
    up a second worker container would double the host cost and force
    a shared secret + URL setup just for one minute-resolution job.
  - The reminders volume is small (tens of pending rows per user); a
    SELECT every 60s with a tight WHERE is well below 1% CPU.
  - If the service restarts (deploy), we don't lose anything — the next
    tick re-scans the same pending rows. `notified_at` is the idempotency
    guard so we never double-fire after a restart that happened just
    after sendMessage returned 200.

If we ever need horizontal scale (multiple FastAPI replicas), this loop
must be moved out — multiple replicas would each fire every reminder.
Right now Waiter Note runs a single replica so it's safe.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Optional

from sqlalchemy import select

from models import Reminder, User, async_session
from services.telegram_bot import send_message
from utils.time import utc_ts


# How often to wake up and scan. One minute is the resolution promised
# by the UI ("за 5 минут / за 15 минут …" presets); finer ticks would
# just cost more DB queries without anyone noticing.
_TICK_SECONDS = 60

# Grace window: if for some reason a notification didn't fire on time
# (deploy outage, DB blip, app paused), still send it as long as the
# original `remind_at` is no more than an hour in the past. Beyond that
# the user has presumably noticed the absence and the notification is
# stale.
_GRACE_SECONDS = 3600

# Per-tick safety cap on rows processed. Stops a single pathological
# tick (e.g. someone scripted 10k reminders all due now) from monopolising
# the event loop and blocking real HTTP requests. Anything not processed
# in this tick rolls over to the next one.
_MAX_PER_TICK = 200


def _log(msg: str) -> None:
    # Plain print so the lines show up on Railway / any PaaS without
    # forcing a logging config on the rest of the project. Matches the
    # convention in services/telegram_bot.py.
    print(f"[reminders-worker] {msg}", flush=True)


def _format_message(text: str) -> str:
    """The notification body. Plain text — no Markdown/HTML so we don't
    need to escape special characters in the user's reminder text."""
    # Bell emoji + the user's own text. Keep it short so it reads well in
    # a Telegram push preview on the lockscreen.
    return f"🔔 Напоминание\n\n{text}"


async def _tick() -> int:
    """
    Run one scan. Returns the number of notifications actually sent.

    Logic:
      • Find pending reminders whose (remind_at - lead_minutes*60) is in
        the past, bounded by the grace window so we don't fire stale
        ones from days ago.
      • For each, look up the user's tg_id, then call sendMessage.
      • On success → set notified_at = now. On Telegram-side failure
        (blocked, unreachable) → still set notified_at so we don't loop
        forever trying. send_message() already logs the reason.

    All work is done under ONE session per tick — a single transaction
    keeps the DB load low and groups commits.
    """
    now = utc_ts()
    cutoff_due = now  # notify_at <= now
    cutoff_grace = now - _GRACE_SECONDS  # but remind_at >= now - 1h

    async with async_session() as session:
        # JOIN onto User so we have tg_id in one query rather than N+1.
        stmt = (
            select(Reminder, User.tg_id)
            .join(User, User.id == Reminder.user_id)
            .where(
                Reminder.is_done.is_(False),
                Reminder.notified_at.is_(None),
                # SQL-side: remind_at - lead_minutes*60 <= now
                (Reminder.remind_at - Reminder.lead_minutes * 60) <= cutoff_due,
                # Skip very-late ones — the user has noticed by now.
                Reminder.remind_at >= cutoff_grace,
            )
            .order_by(Reminder.remind_at.asc())
            .limit(_MAX_PER_TICK)
        )
        rows = list((await session.execute(stmt)).all())

        if not rows:
            return 0

        sent = 0
        for reminder, tg_id in rows:
            if not tg_id:
                # Edge case: a user row with no tg_id. Shouldn't happen
                # (we set it on first /me) but if it does, don't loop.
                reminder.notified_at = now
                continue

            ok = await send_message(tg_id, _format_message(reminder.text))
            # Set notified_at regardless of success — see docstring. The
            # bot module already logged why it failed.
            reminder.notified_at = now
            if ok:
                sent += 1

        await session.commit()
        return sent


async def _run_loop(stop_event: asyncio.Event) -> None:
    """
    The main loop. Sleeps in short slices so a shutdown signal is
    reacted to within ~1 second, not the full _TICK_SECONDS interval.

    A bare `await asyncio.sleep(60)` would mean uvicorn waits up to 60s
    on SIGTERM before the worker honors the cancel; the slice-based
    sleep keeps Railway deploys snappy.
    """
    _log("worker started")
    try:
        while not stop_event.is_set():
            try:
                sent = await _tick()
                if sent > 0:
                    _log(f"sent {sent} notifications")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                # Never let the loop die on a transient error. A failed
                # tick is logged and we try again next minute.
                _log(f"tick failed: {type(e).__name__}: {e}")

            # Sliced sleep so SIGTERM doesn't wait a full minute.
            for _ in range(_TICK_SECONDS):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1)
    finally:
        _log("worker stopped")


# Module-level handle so the lifespan can hold a reference and cancel it.
_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def start() -> None:
    """Spawn the worker task. Idempotent: a second call is a no-op."""
    global _task, _stop_event
    if _task is not None and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_run_loop(_stop_event), name="reminders-worker")


async def stop() -> None:
    """Signal the worker to stop and await its exit. Safe to call
    multiple times."""
    global _task, _stop_event
    if _task is None:
        return
    if _stop_event is not None:
        _stop_event.set()
    # Belt-and-braces: also cancel directly in case the loop is stuck in
    # a long-running send_message call.
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
    _stop_event = None
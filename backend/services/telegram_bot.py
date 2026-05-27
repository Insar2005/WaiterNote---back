"""
Minimal Telegram Bot API helpers.

We use this for one thing right now: check whether the bot is allowed to
send a message to a given user. A user must press /start in the bot at
least once before the bot can initiate a conversation — until then
Telegram rejects sendMessage / sendChatAction with 403 Forbidden.

We use sendChatAction (action="typing") as the probe because:
  - It's the lightest call: ~no visible side effect (the "typing…"
    indicator disappears within a few seconds and many clients don't
    even render a single transient probe).
  - It returns the same auth signals as sendMessage: 403 when the user
    blocked the bot or never started it, 200 OK otherwise.

Why this file has retries, caching and logs (not just one POST):
  - Our backend lives on a managed PaaS where outbound TCP/TLS can be
    slow, especially on the first call after the container has been
    idle. A single 5s probe was timing out ~half the time.
  - Hitting api.telegram.org on EVERY page load is also wasteful: most
    users will not block the bot mid-session, so a short positive cache
    (1 minute) makes the gate effectively free for the common case.

We deliberately do NOT pull in aiogram / python-telegram-bot just for
two endpoints; aiohttp is enough and keeps the deploy lean.
"""
from __future__ import annotations

import asyncio
import time
import aiohttp
from typing import Literal, Optional

from config import get_settings

# Per-attempt cap. Two attempts back-to-back give us up to ~20s in the
# worst case — but in practice the cold path completes well under one
# of these and the cached path is instantaneous.
_ATTEMPT_TIMEOUT_SECONDS = 10.0
_MAX_ATTEMPTS = 2

# Positive-result cache: once we've confirmed a user CAN be messaged we
# trust that for a short window. A user could block the bot during this
# window, but the worst outcome is one failed notification — far better
# than gating the app on every page load while Telegram is slow.
# We deliberately do NOT cache 'blocked' — when the user comes back from
# the bot after pressing /start we want the next probe to see 'ok' right
# away, not wait for a TTL to expire.
_OK_CACHE_TTL_SECONDS = 60

# tg_id -> (cached_status, expires_at_monotonic)
_ok_cache: dict[int, tuple[str, float]] = {}


BotProbeResult = Literal["ok", "blocked", "unreachable"]


def _log(msg: str) -> None:
    # Plain print so the lines show up in PaaS logs without needing the
    # whole project to configure logging.
    print(f"[bot-probe] {msg}", flush=True)


async def _probe_once(token: str, tg_user_id: int) -> BotProbeResult:
    """One attempt of sendChatAction. Returns ok/blocked/unreachable."""
    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    payload = {"chat_id": tg_user_id, "action": "typing"}

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_ATTEMPT_TIMEOUT_SECONDS),
        ) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return "ok"

                # Explicit "no" from Telegram. The user must (re-)open
                # the bot and press /start.
                if resp.status == 403:
                    return "blocked"

                # "chat not found" — same meaning as 403 for our purposes.
                if resp.status == 400:
                    try:
                        data = await resp.json()
                        desc = (data or {}).get("description", "").lower()
                        if "chat not found" in desc:
                            return "blocked"
                        _log(f"400 from Telegram: {desc!r}")
                    except Exception:  # noqa: BLE001
                        pass
                    return "unreachable"

                _log(f"unexpected status {resp.status}")
                return "unreachable"
    except asyncio.TimeoutError:
        _log(f"timeout after {_ATTEMPT_TIMEOUT_SECONDS}s")
        return "unreachable"
    except Exception as e:  # noqa: BLE001
        _log(f"transport error: {type(e).__name__}: {e}")
        return "unreachable"


async def check_bot_can_message(tg_user_id: int) -> BotProbeResult:
    """
    Probe whether the bot can write to tg_user_id right now.

    Short-circuits on a recent 'ok' for the same user. Retries once on
    'unreachable' since the most common failure mode is a flaky cold-
    start TLS handshake to api.telegram.org, which usually clears on
    a second try inside the same request.
    """
    settings = get_settings()
    token = settings.BOT_TOKEN
    if not token:
        _log("BOT_TOKEN is empty — returning unreachable")
        return "unreachable"

    # Short positive cache: avoid hammering Telegram on every page load.
    cached = _ok_cache.get(tg_user_id)
    if cached:
        status, expires_at = cached
        if expires_at > time.monotonic() and status == "ok":
            return "ok"
        # Expired entry — drop it lazily.
        _ok_cache.pop(tg_user_id, None)

    last: BotProbeResult = "unreachable"
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        result = await _probe_once(token, tg_user_id)
        last = result
        if result in ("ok", "blocked"):
            # Definitive answer — no point retrying.
            if result == "ok":
                _ok_cache[tg_user_id] = (
                    "ok",
                    time.monotonic() + _OK_CACHE_TTL_SECONDS,
                )
            _log(f"user={tg_user_id} attempt={attempt} -> {result}")
            return result
        # 'unreachable' — give it one more shot before giving up.
        _log(f"user={tg_user_id} attempt={attempt} -> unreachable, will retry")

    _log(f"user={tg_user_id} all attempts failed -> {last}")
    return last


async def get_bot_username() -> Optional[str]:
    """
    Return the bot's @username via getMe. Cached on the settings object
    so the first successful call serves every subsequent request in this
    process. Failures aren't cached — we'll try again later.
    """
    settings = get_settings()
    cached = getattr(settings, "_cached_bot_username", None)
    if cached:
        return cached  # successful previous lookup

    token = settings.BOT_TOKEN
    if not token:
        return None

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_ATTEMPT_TIMEOUT_SECONDS),
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    _log(f"getMe non-200: {resp.status}")
                    return None
                data = await resp.json()
                username = (data or {}).get("result", {}).get("username")
                if username:
                    settings._cached_bot_username = username
                    _log(f"resolved bot username: @{username}")
                return username
    except Exception as e:  # noqa: BLE001
        _log(f"getMe failed: {type(e).__name__}: {e}")
        return None
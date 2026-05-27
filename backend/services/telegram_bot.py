"""
Minimal Telegram Bot API helpers.

We only need one thing right now: check whether the bot is allowed to send
a message to a given user. A user must press /start in the bot at least
once before the bot can initiate a conversation — until then Telegram
rejects sendMessage / sendChatAction with 403 Forbidden.

We use sendChatAction (with "typing") as the probe because:
  - It is the lightest call: no visible side effect for the user — the
    "typing…" indicator disappears within ~5s and many clients don't
    even render it on a probe.
  - It returns the same auth signals as sendMessage: 403 when the user
    blocked the bot or never started it, 200 OK otherwise.

We deliberately do NOT pull in aiogram / python-telegram-bot just for one
endpoint; aiohttp is enough and keeps the deploy lean.
"""
from __future__ import annotations

import aiohttp
from typing import Literal

from config import get_settings

# Cap how long we wait for Telegram. Too long ⇒ /me hangs forever when
# Telegram has a hiccup. Too short ⇒ we falsely report "can't reach Telegram"
# on a slow link. 5s is a comfortable middle ground.
_TIMEOUT_SECONDS = 5.0


BotProbeResult = Literal["ok", "blocked", "unreachable"]


async def check_bot_can_message(tg_user_id: int) -> BotProbeResult:
    """
    Probe whether the bot is currently allowed to write to tg_user_id.

    Returns:
      "ok"          — bot can write to this user (they've pressed /start
                      and haven't blocked the bot).
      "blocked"     — Telegram explicitly says no: user never started the
                      bot, blocked it, or deactivated their account.
                      The frontend should gate the app and ask the user
                      to open the bot.
      "unreachable" — we couldn't reach Telegram or got something we don't
                      understand. The frontend should *not* treat this as
                      "user blocked us" — it surfaces a separate retry UI.
    """
    settings = get_settings()
    token = settings.BOT_TOKEN
    if not token:
        # Misconfigured server — don't pretend the user blocked the bot,
        # but don't claim everything is fine either.
        return "unreachable"

    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    payload = {"chat_id": tg_user_id, "action": "typing"}

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS),
        ) as session:
            async with session.post(url, json=payload) as resp:
                # 200 OK is the happy path. We *could* also parse the JSON
                # body's `ok` field, but the HTTP code already tells us
                # everything we need for the probe.
                if resp.status == 200:
                    return "ok"

                # 403 Forbidden is the signal Telegram returns when:
                #   - "bot was blocked by the user"
                #   - "bot can't initiate conversation with a user"
                #   - "user is deactivated"
                # All of them mean: we can't reach this user via the bot.
                if resp.status == 403:
                    return "blocked"

                # 400 with description "chat not found" also means the
                # user has never interacted with the bot at all.
                if resp.status == 400:
                    try:
                        data = await resp.json()
                        desc = (data or {}).get("description", "").lower()
                        if "chat not found" in desc:
                            return "blocked"
                    except Exception:  # noqa: BLE001
                        pass
                    return "unreachable"

                # Anything else (5xx, weird statuses) — Telegram is in a
                # bad state, don't penalise the user.
                return "unreachable"
    except Exception:  # noqa: BLE001 — network/timeout/SSL: all "unreachable"
        return "unreachable"


async def get_bot_username() -> str | None:
    """
    Resolve the bot's @username via getMe. Result is cached on the settings
    object so we only ever ask Telegram once per process. Used to power
    the "Open @waiternote_bot" deep link on the gate screen — without it
    the client doesn't know which bot to open.
    """
    settings = get_settings()
    cached = getattr(settings, "_cached_bot_username", None)
    if cached is not None:
        return cached or None  # empty string ⇒ we tried and failed

    token = settings.BOT_TOKEN
    if not token:
        return None

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS),
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    settings._cached_bot_username = ""
                    return None
                data = await resp.json()
                username = (data or {}).get("result", {}).get("username")
                settings._cached_bot_username = username or ""
                return username or None
    except Exception:  # noqa: BLE001
        # Don't cache failures — try again on the next request.
        return None
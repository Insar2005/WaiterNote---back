"""
Telegram WebApp initData validation.

Historically this module hand-rolled the HMAC-SHA256 check. That broke for
Mini Apps launched as a "Main Mini App" (initData carries `signature`,
`chat_type`, no `query_id`): the `user` field is a JSON string whose inner
slashes are escaped as `\\/`, and Telegram computes the hash over that
escaped form. Reproducing Telegram's exact normalisation by hand is fragile,
so validation is delegated to the well-tested `init-data-py` package, which
handles both the classic `hash` (HMAC) and the escaping quirks correctly.

The public surface (`parse_and_validate_init_data`, `InitDataParseError`,
`TelegramUser`) is unchanged, so `deps.py` and the routers need no edits.
"""
from typing import TypedDict

from init_data_py import InitData
from init_data_py import errors as ide_errors


class TelegramUser(TypedDict, total=False):
    id: int
    first_name: str
    last_name: str
    username: str
    language_code: str
    is_premium: bool


class InitDataParseError(Exception):
    """Raised when initData is malformed, expired, or its signature is invalid."""


def parse_and_validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int,
) -> TelegramUser:
    """
    Validate Telegram WebApp initData and return the embedded user.

    Uses `init-data-py` for the cryptographic check. `max_age_seconds` is
    passed through as the freshness window (`lifetime`); a value <= 0
    disables the expiry check.

    Raises InitDataParseError on any failure (malformed, expired, bad hash,
    or missing user) — same exception the rest of the codebase already
    catches in deps.py.
    """
    if not init_data:
        raise InitDataParseError("empty initData")

    # Parse the query string into an InitData object.
    try:
        parsed = InitData.parse(init_data)
    except ide_errors.UnexpectedFormatError as e:
        raise InitDataParseError("malformed initData") from e
    except Exception as e:  # noqa: BLE001 - any parse failure is a client error
        raise InitDataParseError(f"could not parse initData: {e}") from e

    # Validate the signature (and freshness, unless disabled).
    # `lifetime=None` disables the expiry check; the library otherwise
    # rejects data older than `lifetime` seconds.
    lifetime = max_age_seconds if max_age_seconds and max_age_seconds > 0 else None
    try:
        is_valid = parsed.validate(bot_token, lifetime=lifetime, raise_error=True)
    except ide_errors.SignMissingError as e:
        raise InitDataParseError("hash field is missing") from e
    except ide_errors.SignInvalidError as e:
        raise InitDataParseError("hash mismatch") from e
    except ide_errors.ExpiredError as e:
        raise InitDataParseError("initData expired") from e
    except ide_errors.AuthDateMissingError as e:
        raise InitDataParseError("auth_date field is missing") from e
    except InitDataParseError:
        raise
    except Exception as e:  # noqa: BLE001
        raise InitDataParseError(f"initData validation failed: {e}") from e

    if not is_valid:
        raise InitDataParseError("hash mismatch")

    # Extract the user.
    user = parsed.user
    if user is None:
        raise InitDataParseError("user field is missing")
    if getattr(user, "id", None) is None:
        raise InitDataParseError("user.id is missing")

    result: TelegramUser = {"id": user.id}
    # Optional fields — copy through whatever Telegram supplied.
    for attr in ("first_name", "last_name", "username", "language_code", "is_premium"):
        value = getattr(user, attr, None)
        if value is not None:
            result[attr] = value  # type: ignore[literal-required]

    return result
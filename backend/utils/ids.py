import re
import secrets

# nanoid default alphabet: A-Za-z0-9_-
_NANOID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
_NANOID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{21}$")


def is_valid_id(value: str) -> bool:
    """Validate that string is a valid nanoid(21)."""
    return bool(_NANOID_PATTERN.match(value))


def new_id() -> str:
    """
    Generate a 21-character nanoid using the standard URL-safe alphabet.
    We use secrets.choice for cryptographically-strong randomness — IDs
    can leak into URLs/logs and we don't want them to be guessable.
    """
    return "".join(secrets.choice(_NANOID_ALPHABET) for _ in range(21))